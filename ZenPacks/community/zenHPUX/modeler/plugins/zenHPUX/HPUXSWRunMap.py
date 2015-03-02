from Products.DataCollector.plugins.CollectorPlugin import SnmpPlugin, GetTableMap
from Products.ZenModel.OSProcessMatcher import buildObjectMapData
from ZenPacks.community.ConstructionKit.CustomComponent import getProcessIdentifier
from ZenPacks.community.zenHPUX.Definition import *
import re

__doc__ = """HPUXSWRunMap

HPUXSWRunMap detects HPUX OSProcess components

"""

HRSWRUNENTRY = '.1.3.6.1.4.1.11.2.3.1.4.2.1'
    
class HPUXSWRunMap(SnmpPlugin):
    ''''''
    compname = "os"
    constr = Construct(HPUXProcessDefinition)
    relname = constr.relname
    modname = constr.zenpackComponentModule
    baseid = constr.baseid
    collector = 'zenhpuxprocess'
    
    deviceProperties = SnmpPlugin.deviceProperties + ('osProcessClassMatchData',)

    columns = {
         '.22': 'procName',
         }
    
    hrswrunentry = HRSWRUNENTRY
    
    snmpGetTableMaps = (
        GetTableMap('processTable', HRSWRUNENTRY, columns),
    )
    
    def _extractProcessText(self, proc):
        path = proc.get('procName','').strip()
        name = path.strip()
        if name: 
            return name.rstrip()
        else:
            self._log.warn("Skipping process with no name")
            
    def process(self, device, results, log):
        """
        Process the SNMP information returned from a device
        """
        self._log = log
        log.info('HRSWRunMap Processing %s for device %s', self.name(), device.id)
        getdata, tabledata = results
        log.debug("%s tabledata = %s", device.id, tabledata)

        # get the SNMP process data
        pidtable = tabledata.get("processTable")
        if pidtable is None:
            log.error("Unable to get data for %s from hrSWRunEntry %s"
                          " -- skipping model", HRSWRUNENTRY, device.id)
            return None

        log.debug("=== Process information received ===")
        for p in sorted(pidtable.keys()):
            log.debug("snmpidx: %s\tprocess: %s" % (p, pidtable[p]))

        if not pidtable.values():
            log.warning("No process information from hrSWRunEntry %s",
                        HRSWRUNENTRY)
            return None

        cmds = map(self._extractProcessText, pidtable.values())
        cmds = filter(lambda(cmd):cmd, cmds)
        rm = self.relMap()
        matchData = device.osProcessClassMatchData
        log.debug(matchData)
        rm.extend(map(self.objectMap, buildObjectMapData(matchData, cmds)))
        return rm

