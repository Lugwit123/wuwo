# coding:utf-8
from __future__ import print_function   
import os,re,sys,codecs,json
import shutil
import ctypes
import subprocess
import time

def get_long_path(short_path):
    # 创建一个缓冲区来存储转换后的路径
    if not short_path:
        return ""
    print("short_path",short_path)
    buffer = ctypes.create_unicode_buffer(260)  # MAX_PATH for Windows
    get_long_path_name = ctypes.windll.kernel32.GetLongPathNameW

    # 调用 Windows API 将短路径转换为长路径
    result = get_long_path_name(short_path, buffer, 260)
    if result == 0:
        # 如果转换失败，返回原始路径
        return short_path
    return buffer.value

curDir=os.path.dirname(__file__)
LugwitToolDir=re.search('.+trayapp',__file__).group()
LugwitToolDir=get_long_path(LugwitToolDir)
python_envDir=os.path.dirname(LugwitToolDir)+'\\python_env'

curDir = os.path.dirname(__file__)

if get_long_path(os.getenv('LugwitToolDir','.')).lower() != LugwitToolDir.lower():
    print("LugwitToolDir is not {},set env var".format(LugwitToolDir),os.getenv('LugwitToolDir'))
    os.system('setx LugwitToolDir '+LugwitToolDir)


def get_my_documents():
    import os
    from ctypes import windll, create_unicode_buffer
    CSIDL_PERSONAL = 5
    SHGFP_TYPE_CURRENT = 0

    buf = create_unicode_buffer(260)  # MAX_PATH = 260
    windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)

    return buf.value

documentsPath = get_my_documents()


userDir=os.path.expandvars("%USERPROFILE%")
if userDir == "C:\\Windows\\system32\\config\\systemprofile":
    userDir = r"C:\Users\Administrator.OC"
print ("userDir",userDir,__file__)

oriEnvVarFile=userDir+r'/.Lugwit/config/oriEnvVar.json'
print ('oriEnvVarFile',oriEnvVarFile,__file__)
os.environ['oriEnvVarFile']=oriEnvVarFile

plugDocDir_user = userDir+'/.Lugwit'
plugConfigDir_user = plugDocDir_user+'/config'
plugDataDir_user = plugDocDir_user+'/data'
if sys.version_info[0]==3:
    os.makedirs(plugDocDir_user,exist_ok=True)
    os.makedirs(plugConfigDir_user,exist_ok=True)
    os.makedirs(plugDataDir_user,exist_ok=True)



oriEnvVarJsonFile=os.path.join(os.environ.get('WUWO_CONFIG_DIR', os.path.join(LugwitToolDir, 'config')), "EnvVar_orgi.json")
ToolEnvJsonFile=os.path.join(plugConfigDir_user,'ToolEnv.json')
ToolEnvJsonFile_orgi=os.path.join(os.environ.get('WUWO_CONFIG_DIR', os.path.join(LugwitToolDir, 'config')), 'ToolEnv_orgi.json')
print(ToolEnvJsonFile_orgi,"ToolEnvJsonFile_orgi")

Lugwit_PluginPath = ""
        
__all__=['LugwitToolDir',
         'oriEnvVarJsonFile',
         'ToolEnvJsonFile',
         'ToolEnvJsonFile_orgi',
         'python_envDir',"Lugwit_PluginPath", "Lugwit_publicPath"]

# 把 lugwit_env rez 包注入的环境变量也导出到当前命名空间
_lugwit_env_keys = [
    'TD_DepotDir', 'Lugwit_publicPath', 'LugwitAppDir', 'LugwitLibDir',
    'LugwitPath', 'Lugwit_mayaPluginPath', 'Yplug', 'P4CHARSET',
    'DEADLINE_PATH', 'NUKE_PATH',
]
names = locals()
for _k in _lugwit_env_keys:
    _v = os.environ.get(_k, '')
    if _v:
        names[_k] = _v
        __all__.append(_k)

names = locals()

set_commands = []
set_commands.append('set LugwitToolDir={}'.format(LugwitToolDir))




# EnvVar_orgi.json 的路径变量已由 lugwit_env rez 包在启动时注入，无需在此重复加载。

shutil.copyfile(ToolEnvJsonFile_orgi,ToolEnvJsonFile) if not os.path.exists(ToolEnvJsonFile) else None
print(ToolEnvJsonFile,"ToolEnvJsonFile")
with codecs.open(ToolEnvJsonFile,'r','utf-8') as f:
    configJson=json.load(f)
    configJson['LugwitToolDir']=LugwitToolDir
    for key,val in configJson.items():
        # 使用 os.path.expandvars 处理 %VAR% 格式的环境变量
        expanded_val = os.path.expandvars(str(val))
        try:
            os.environ[str(key)]=str(expanded_val)
            names[str(key)]=expanded_val
            __all__.append(key)
        except:
            pass

if os.getenv("is_maya_dev")=="1":
    names['Lugwit_mayaPluginPath']=r'D:\TD_Depot\plug_in\Lugwit_plug\mayaPlug_dev'
    os.environ['Lugwit_mayaPluginPath']=r'D:\TD_Depot\plug_in\Lugwit_plug\mayaPlug_dev'

os.environ['documentsPath']=documentsPath
__all__.append('documentsPath')
names['documentsPath']=documentsPath

def gen_env_var_bat_file():
    env={x:os.environ.get(x,'') for x in __all__}
    env_bat=os.path.expandvars('%Temp%\\env.bat')
    with codecs.open(env_bat,'w','utf-8') as f:
        f.write('@echo off\n')
        for k,v in env.items():
            f.write('set {}={}\n'.format(k,v))
    

# if __name__=="__main__":
#     import fire
#     fire.Fire()

