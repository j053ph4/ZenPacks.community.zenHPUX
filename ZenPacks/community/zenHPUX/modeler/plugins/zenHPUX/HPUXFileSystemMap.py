import re
from Products.DataCollector.plugins.CollectorPlugin import SnmpPlugin, GetTableMap
from Products.DataCollector.plugins.DataMaps import ObjectMap
import Globals

__doc__ = """HPUXFileSystemMap

HPUXFileSystemMap detects HPUX Filesystem components

"""


class HPUXFileSystemMap(SnmpPlugin):

    maptype = "FileSystemMap"
    compname = "os"
    relname = "filesystems"
    modname = "Products.ZenModel.FileSystem"

    columns = {
         '.1': 'snmpindex',
         '.2': 'type',
         '.4': 'totalBlocks',
         '.7': 'blockSize',
         '.10': 'mount',
         }

    ocolumns = {
         '.1': 'snmpindex',
         '.2': 'type',
         '.3': 'storageDevice',
         '.4': 'totalBlocks',
         '.5': 'blocksFree',
         '.6': 'blocksAvail',
         '.7': 'blockSize',
         '.8': 'totalFiles',
         '.9': 'filesFree',
         '.10': 'mount',
         }

    fstypemap = {
        0: 'hfs',
        7: 'vxfs',
        }

    snmpGetTableMaps = (
        GetTableMap('fsTableOid', '.1.3.6.1.4.1.11.2.3.1.2.2.1', columns),
    )
    
    def process(self, device, results, log):
        """collect snmp information from this device"""
        getdata, tabledata = results
        fstable = tabledata.get("fsTableOid")
        skipfsnames = getattr(device, 'zFileSystemMapIgnoreNames', None)
        skipfstypes = getattr(device, 'zFileSystemMapIgnoreTypes', None)
        maps = []
        rm = self.relMap()
        for fs in fstable.values():
            if not fs.has_key("totalBlocks"): continue
            if not self.checkColumns(fs, self.columns, log): continue
            if skipfsnames and re.search(skipfsnames, fs['mount']):
                log.info("Skipping %s as it matches zFileSystemMapIgnoreNames.",
                    fs['mount'])
                continue

            if skipfstypes and fs['type'] in skipfstypes:
                log.info("Skipping %s (%s) as it matches zFileSystemMapIgnoreTypes.",
                    fs['mount'], fs['type'])
                continue

            fs['snmpindex'] = '%s.%s' % (fs['snmpindex'],fs['type'])
            fs['type'] = self.fstypemap.get(fs['type'],None)
            size = long(fs['blockSize'] * fs['totalBlocks'])
            if size > 0:
                om = self.objectMap(fs)
                om.id = self.prepId(om.mount)
                rm.append(om)
        maps.append(rm)
        return maps
