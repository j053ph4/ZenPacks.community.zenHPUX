from ZenPacks.community.ConstructionKit.ClassHelper import *

def HPUXProcessgetEventClassesVocabulary(context):
    return SimpleVocabulary.fromValues(context.listgetEventClasses())

class HPUXProcessInfo(ClassHelper.HPUXProcessInfo):
    ''''''


