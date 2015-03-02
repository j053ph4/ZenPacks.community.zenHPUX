import logging
log = logging.getLogger('zen.zenhpuxprocess')
from Products.ZenCollector.services.config import CollectorConfigService
from Products.ZenHub.services.ProcessConfig import *
from ZenPacks.community.zenHPUX.Definition import *

class HPUXProcessConfig(ProcessConfig):
    
    constr = Construct(HPUXProcessDefinition)
    relname = constr.relname

    def _createDeviceProxy(self, device):
        #procs = device.getMonitoredComponents(collector='zenhpuxprocess')
        procs = device.os.hPUXProcesss()
        if not procs:
            log.debug("Device %s has no monitored processes -- ignoring",
                      device.titleOrId())
            return None

        proxy = CollectorConfigService._createDeviceProxy(self, device)
        proxy.configCycleInterval = self._prefs.processCycleInterval

        proxy.name = device.id
        proxy.lastmodeltime = device.getLastChangeString()
        proxy.thresholds = []
        proxy.processes = {}
        proxy.snmpConnInfo = device.getSnmpConnInfo()
        for p in procs:
            # Find out daemon is responsible for this process
            # by counting the number of SNMP data sources in the template
            # if SNMP is not responsible, then do not add it to the list
            snmpMonitored = False
            for rrdTpl in p.getRRDTemplates():
                if len(rrdTpl.getRRDDataSources("SNMP")) > 0:
                    snmpMonitored = True
                    break

            # In case the process is not SNMP monitored
            if not snmpMonitored:
                log.debug("Skipping process %r - not an SNMP monitored process", p)
                continue

            # In case the catalog is out of sync above
            if not p.monitored():
                log.debug("Skipping process %r - zMonitor disabled", p)
                continue
            includeRegex = getattr(p.osProcessClass(), 'includeRegex', False)
            excludeRegex = getattr(p.osProcessClass(), 'excludeRegex', False)
            replaceRegex = getattr(p.osProcessClass(), 'replaceRegex', False)
            replacement  = getattr(p.osProcessClass(), 'replacement', False)
            generatedId  = getattr(p, 'generatedId', False)
            primaryUrlPath = getattr(p.osProcessClass(), 'processClassPrimaryUrlPath', False)
            if primaryUrlPath: primaryUrlPath = primaryUrlPath()

            if not includeRegex:
                log.warn("OS process class %s has no defined regex, this process not being monitored",
                         p.getOSProcessClass())
                continue
            bad_regex = False
            for regex in [includeRegex, excludeRegex, replaceRegex]:
                if regex:
                    try:
                        re.compile(regex)
                    except re.error as ex:
                        log.warn(
                            "OS process class %s has an invalid regex (%s): %s",
                            p.getOSProcessClass(), regex, ex)
                        bad_regex = True
                        break
            if bad_regex:
                continue

            proc = ProcessProxy()
            proc.includeRegex = includeRegex
            proc.excludeRegex = excludeRegex
            proc.replaceRegex = replaceRegex
            proc.replacement = replacement
            proc.primaryUrlPath = primaryUrlPath
            proc.generatedId = generatedId
            proc.name = p.id
            proc.originalName = p.name()
            try: proc.restart = p.alertOnRestart()
            except:
                try: proc.restart = p.zAlertOnRestart
                except:
                    try: proc.restart = p.zAlertOnRestarts
                    except: proc.restart = False
            try: proc.severity = p.getFailSeverity()
            except: proc.severity = 3
            proc.processClass = p.getOSProcessClass()
            proxy.processes[p.id] = proc
            proxy.thresholds.extend(p.getThresholdInstances('SNMP'))

        if proxy.processes:
            return proxy
    @onUpdate(OSProcessClass)
    def processClassUpdated(self, object, event):
        devices = set()
        for process in object.instances():
            device = process.device()
            if not device:
                continue
            device = device.primaryAq()
            device_path = device.getPrimaryUrlPath()
            if not device_path in devices:
                self._notifyAll(device)
                devices.add(device_path)

    @onUpdate(OSProcessOrganizer)
    def processOrganizerUpdated(self, object, event):
        catalog = ICatalogTool(object.primaryAq())
        results = catalog.search(OSProcessClass)
        if not results.total:
            return
        devices = set()
        for organizer in results:
            if results.areBrains:
                organizer = organizer.getObject()
            for process in organizer.instances():
                device = process.device()
                if not device:
                    continue
                device = device.primaryAq()
                device_path = device.getPrimaryUrlPath()
                if not device_path in devices:
                    self._notifyAll(device)
                    devices.add(device_path)
