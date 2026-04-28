"""
_update_config.py
Called by install.bat to update config.yaml with default rez package paths.
Usage: python _update_config.py <config_yaml> <build_path> <release_path>
"""
import re
import sys

if len(sys.argv) != 4:
    print("Usage: python _update_config.py <config_yaml> <build_path> <release_path>")
    sys.exit(1)

config_file = sys.argv[1]
build_path  = sys.argv[2].replace("\\", "/")
release_path = sys.argv[3].replace("\\", "/")

with open(config_file, encoding="utf-8") as f:
    content = f.read()

content = re.sub(r'(?<=build:\s{0,10}")([^"]+)(?=")',   build_path,   content)
content = re.sub(r'(?<=release:\s{0,10}")([^"]+)(?=")', release_path, content)

with open(config_file, "w", encoding="utf-8") as f:
    f.write(content)

print(f"[OK] config.yaml updated:")
print(f"     build:   {build_path}")
print(f"     release: {release_path}")
