import logging
log = logging.getLogger('zen.zenhpuxprocess')

import Globals
import zope.component
import zope.interface
from twisted.internet import base, defer, reactor
from twisted.python.failure import Failure
from Products.ZenCollector.daemon import CollectorDaemon
from Products.ZenCollector.interfaces import ICollectorPreferences, IScheduledTask, IEventService, IDataService
from Products.ZenCollector.tasks import SimpleTaskFactory, SimpleTaskSplitter, TaskStates
from Products.ZenEvents.Event import Warning, Clear
from Products.ZenUtils.observable import ObservableMixin
from Products.ZenUtils.Utils import unused
from Products.ZenUtils.Driver import drive
from ZenPacks.community.zenHPUX.services.HPUXProcessConfig import *
from Products.ZenRRD.zenprocess import *

unused(Globals)
unused(HPUXProcessConfig)

#global HOSTROOT
HOSTROOT = '.1.3.6.1.4.1.11.2.3.1'
#global RUNROOT
RUNROOT  = HOSTROOT + '.4'
#global NAMETABLE
NAMETABLE  = RUNROOT + '.2.1.22'
#global PATHTABLE
PATHTABLE  = RUNROOT + '.2.1.22'
#global ARGSTABLE
ARGSTABLE  = RUNROOT + '.2.1.22'
#global CPU
CPU = RUNROOT + '.2.1.25.'        # note trailing dot
#global MEM
MEM = RUNROOT + '.2.1.28.'        # note trailing dot

def mapResultsToDicts(showrawtables, results):
    """
    Parse the process tables and reconstruct the list of processes
    that are on the device.

    @parameter showrawtables: log the raw table info?
    @type showrawtables: boolean
    @parameter results: results of SNMP table gets ie (OID + pid, value)
    @type results: dictionary of dictionaries
    @return: maps relating names and pids to each other
    @rtype: dictionary, list of tuples
    """
    
    def extract(dictionary, oid, value):
        """
        Helper function to extract SNMP table data.
        """
        pid = int(oid.rsplit('.', 1)[-1])
        dictionary[pid] = str(value).strip()
    
    names, paths, args = {}, {}, {}
    if showrawtables: log.info("NAMETABLE = %r", results[NAMETABLE])
    
    for row in results[NAMETABLE].iteritems():
        oid = row[0]
        process = row[1]
        pparts = process.split(' ')
        
        name = pparts[0].split('/')[-1]
        extract(names, oid, name)
        
        path = pparts[0]
        extract(paths, oid, path)
        
        arguments = " ".join(pparts[1:])
        extract(args, oid, arguments)
        
    procs = []
    for pid, name in names.iteritems():
        path = paths.get(pid, '')
        if path and path.find('\\') == -1: name = path
        arg = args.get(pid, '')
        procs.append( (pid, ( name + " " + arg).strip() ) )
    log.debug("args: %s" % args)
    log.debug("procs: %s" % procs)
    return args, procs


class HPUXProcessPreferences(object):
    zope.interface.implements(ICollectorPreferences)
    def __init__(self):
        """
        Constructs a new HPUXProcessPreferences instance and provide default
        values for needed attributes.
        """
        self.collectorName = "zenhpuxprocess"
        self.defaultRRDCreateCommand = None
        self.cycleInterval = 180 # seconds
        self.configCycleInterval = 20 # minutes
        self.options = None
        self.configurationService = 'ZenPacks.community.zenHPUX.services.HPUXProcessConfig'
    
    def buildOptions(self, parser): pass
     
    def postStartup(self): pass

class HPUXProcessTask(ZenProcessTask):
    ''''''
    def __init__(self, deviceId, taskName, scheduleIntervalSeconds, taskConfig):
        super(ZenProcessTask, self).__init__()
        
        #needed for interface
        self.name = taskName
        self.configId = deviceId
        self.interval = scheduleIntervalSeconds
        self.state = TaskStates.STATE_IDLE
        
        #the task config corresponds to a DeviceProxy
        self._device = taskConfig
        self._devId = self._device.name
        self._manageIp = self._device.manageIp
        self._maxOidsPerRequest = self._device.zMaxOIDPerRequest
        
        self._dataService = zope.component.queryUtility(IDataService)
        self._eventService = zope.component.queryUtility(IEventService)
        self._preferences = zope.component.queryUtility(ICollectorPreferences,
                                                        "zenhpuxprocess")
        self.snmpProxy = None
        self.snmpConnInfo = self._device.snmpConnInfo
        
        self._deviceStats = ZenProcessTask.DEVICE_STATS.get(self._devId)
        if self._deviceStats:
            self._deviceStats.update(self._device)
        else:
            self._deviceStats = DeviceStats(self._device)
            ZenProcessTask.DEVICE_STATS[self._devId] = self._deviceStats
    
    @defer.inlineCallbacks
    def _collectCallback(self):
        """
        Callback called after a connect or previous collection so that another
        collection can take place.
        """
        log.debug("_collectCallback")
        log.debug("Scanning %s for processes from %s [%s]" % (NAMETABLE,
                  self._devId, self._manageIp))
        
        self.state = ZenProcessTask.STATE_SCANNING_PROCS
        tables = [NAMETABLE, PATHTABLE, ARGSTABLE]
        try:
            tableResult = yield self._getTables(tables)
            summary = 'Process table up for device %s' % self._devId
            self._clearSnmpError("%s - timeout cleared" % summary, 'table_scan_timeout')
            if self.snmpConnInfo.zSnmpVer == 'v3':
                self._clearSnmpError("%s - v3 error cleared" % summary, 'table_scan_v3_error')
            processes = self._parseProcessNames(tableResult)
            self._clearSnmpError(summary, 'resource_mib')
            self._deviceStats.update(self._device)
            processStatuses = self._determineProcessStatus(processes)
            self._sendProcessEvents(processStatuses)
            self._clearSnmpError(summary)
            yield self._fetchPerf()
            log.debug("Device %s [%s] scanned successfully",
                      self._devId, self._manageIp)
            log.debug("Device %s [%s] results: %s",
                      self._devId, self._manageIp, tableResult)
        except HostResourceMIBExecption as e:
            summary = 'Device %s does not publish HOST-RESOURCES-MIB' %\
                      self._devId
            resolution = "Verify with snmpwalk %s %s" %\
                         (self._devId, NAMETABLE )
            log.warn(summary)
            self._sendSnmpError(summary, "resource_mib", resolution=resolution)
        
        except error.TimeoutError as e:
            log.debug('Timeout fetching tables on device %s' % self._devId)
            self._sendSnmpError('%s; Timeout on device' % PROC_SCAN_ERROR % self._devId, 'table_scan_timeout')
        except Snmpv3Error as e:
            msg = "Cannot connect to SNMP agent on {0._devId}: {1.value}".format(self, str(e))
            log.debug(msg)
            self._sendSnmpError('%s; %s' % (PROC_SCAN_ERROR % self._devId, msg), 'table_scan_v3_error')
        except Exception as e:
            log.exception('Unexpected Error on device %s' % self._devId)
            msg = '%s; error: %s' % (PROC_SCAN_ERROR % self._devId, e)
            self._sendSnmpError(msg)
    
    @defer.inlineCallbacks
    def _fetchPerf(self):
        """
        Get performance data for all the monitored processes on a device
        """
        self.state = ZenProcessTask.STATE_FETCH_PERF
        
        oids = []
        for pid in self._deviceStats.pids:
            oids.extend([CPU + str(pid), MEM + str(pid)])
        if oids:
            singleOids = set()
            results = {}
            oidsToTest = oids
            chunkSize = self._maxOidsPerRequest
            while oidsToTest:
                for oidChunk in chunk(oidsToTest, chunkSize):
                    try:
                        log.debug("%s fetching oid(s) %s" % (self._devId, oidChunk))
                        result = yield self._get(oidChunk)
                        results.update(result)
                    except (error.TimeoutError, Snmpv3Error) as e:
                        log.debug("error reading oid(s) %s - %s", oidChunk, e)
                        singleOids.update(oidChunk)
                oidsToTest = []
                if singleOids and chunkSize > 1:
                    chunkSize = 1
                    log.debug("running oids for %s in single mode %s" % (self._devId, singleOids))
                    oidsToTest = list(singleOids)
            self._storePerfStats(results)
    
    @defer.inlineCallbacks
    def _fetchPerf(self):
        """
        Get performance data for all the monitored processes on a device
        """
        log.debug("_fetchPerf")
        self.state = ZenProcessTask.STATE_FETCH_PERF
        
        oids = []
        for pid in self._deviceStats.pids:
            log.debug('pid: %s' % pid)
            oids.extend([CPU + str(pid), MEM + str(pid)])
        log.debug("oids: %s" % oids)
        if oids:
            singleOids = set()
            results = {}
            oidsToTest = oids
            chunkSize = self._maxOidsPerRequest
            while oidsToTest:
                for oidChunk in chunk(oidsToTest, chunkSize):
                    try:
                        log.debug("%s fetching oid(s) %s" % (self._devId, oidChunk))
                        result = yield self._get(oidChunk)
                        results.update(result)
                    except (error.TimeoutError, Snmpv3Error) as e:
                        log.debug("error reading oid(s) %s - %s", oidChunk, e)
                        singleOids.update(oidChunk)
                oidsToTest = []
                if singleOids and chunkSize > 1:
                    chunkSize = 1
                    log.debug("running oids for %s in single mode %s" % (self._devId, singleOids))
                    oidsToTest = list(singleOids)
            self._storePerfStats(results)
    
    def _determineProcessStatus(self, procs):
        """
        Determine the up/down/restarted status of processes.
        @parameter procs: array of pid, (name_with_args) info
        @type procs: list
        @parameter deviceStats:
        @type procs:
        """
        beforePids = set(self._deviceStats.pids)
        afterPidToProcessStats = {}
        
        for pid, name_with_args in procs:
            log.debug("pid: %s --- name_with_args: %s" % (pid, name_with_args))
            for pStats in self._deviceStats.processStats:
                if pStats._config.name is not None:
                    if pStats.matches(name_with_args):
                        log.debug("Found process %s belonging to %s", name_with_args, pStats._config)
                        afterPidToProcessStats[pid] = pStats
                        break
        
        afterPids = set(afterPidToProcessStats)
        afterByConfig = reverseDict(afterPidToProcessStats)
        
        restarted = {}
        (deadPids, restartedPids, newPids) = determineProcessState(reverseDict(self._deviceStats._pidToProcess), afterByConfig)
        
        restarted = {}
        for restartedPid in restartedPids:
            ZenProcessTask.RESTARTED += 1
            procStats = afterPidToProcessStats[restartedPid]
            pConfig = procStats._config
            
            # only if configured to alert on restarts...
            if pConfig.restart: restarted[procStats] = pConfig
        
        # populate missing (the process set contains 0 processes...)
        missing = []
        for procStat in self._deviceStats.processStats:
            if procStat not in afterByConfig: missing.append(procStat._config)
        
        # For historical reasons, return the beforeByConfig
        beforeByConfig = reverseDict(self._deviceStats._pidToProcess)
        
        return (afterByConfig, afterPidToProcessStats,
                beforeByConfig, newPids, restarted, deadPids, missing)
    
    def _storePerfStats(self, results):
        """
        Save the process performance data in RRD files
        @parameter results: results of SNMP table gets
        @type results: dict of {oid:value} dictionaries
        """
        log.debug('storePerfStats')
        self.state = ZenProcessTask.STATE_STORE_PERF
        byConf = reverseDict(self._deviceStats._pidToProcess)
        for procStat, pids in byConf.iteritems():
            if len(pids) != 1:
                log.debug("There are %d pids by the name %s - %s",
                          len(pids), procStat._config.name, procStat._config.originalName)
            procName = procStat._config.name
            for pid in pids:
                cpu = results.get(CPU + str(pid), None)
                mem = results.get(MEM + str(pid), None)
                procStat.updateCpu(pid, cpu)
                procStat.updateMemory(pid, mem)
            self._save(procName, 'cpu_cpu', procStat.getCpu(),
                       'DERIVE', min=0)
            self._save(procName, 'mem_mem',
                       procStat.getMemory() * 1024, 'GAUGE')
        return results
    
    def _parseProcessNames(self, results):
        """
        Parse the process tables and reconstruct the list of processes
        that are on the device.
        
        @parameter results: results of SNMP table gets
        @type results: dictionary of dictionaries
        """
        log.debug("_parseProcessNames")
        
        self.state = ZenProcessTask.STATE_PARSING_TABLE_DATA
        #log.debug("got results: %s" % results)
        if not results or not results[NAMETABLE]: raise HostResourceMIBExecption()
        
        #if self._preferences.options.captureFilePrefix:
        #    self.capturePacket(self._devId, results)
        
        #showrawtables = self._preferences.options.showrawtables
        args, procs = mapResultsToDicts(True, results)
        #if True:
        #self._showProcessList(procs)
        log.debug("procs: %s" % procs)
        return procs


if __name__ == '__main__':
    myPreferences = HPUXProcessPreferences()

    myTaskFactory = SimpleTaskFactory(HPUXProcessTask)
    myTaskSplitter = SimpleTaskSplitter(myTaskFactory)
    daemon = CollectorDaemon(myPreferences, myTaskSplitter, ConfigListener())
    daemon.run()

