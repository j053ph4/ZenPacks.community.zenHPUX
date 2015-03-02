from ZenPacks.community.ConstructionKit.BasicDefinition import *
from ZenPacks.community.ConstructionKit.Construct import *
from Products.ZenModel.OSProcess import *

def __init__(ob, id, title=None):
    OSProcess.__init__(ob, id, title)
    super(CustomComponent, ob).__init__(id, title)
    
HPUXProcessDefinition = type('HPUXProcessDefinition', (BasicDefinition,), {
        'version' : Version(1, 2, 0),
        'zenpackbase': "zenHPUX",
        'component' : 'HPUXProcess',

        'componentData' : {
                          'singular': 'Process',
                          'plural': 'Processes',
                          'displayed': 'displayName', # component field in Event Console
                          'primaryKey': 'id',
                          'properties': { 
                                        'displayName' : addProperty('Name','Basic',optional='false'),
                                        },
                          },
        'parentClasses' : [ OSProcess ],
        'componentMethods' : [__init__,]
        }
)
