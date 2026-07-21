#!/usr/bin/env python3
"""dao-one-windows · VSIX 打包器(纯 stdlib, zip 条目强制 '/' 分隔符).

用法: python pack_vsix.py <衍生后的扩展目录> <输出.vsix>

VSIX = zip{ extension.vsixmanifest, [Content_Types].xml, extension/** }。
衍生目录里若带 .vsixmanifest(安装产物)则复用为 extension.vsixmanifest 并同步版本号,
否则按 package.json 生成最小清单。
"""
import json
import os
import re
import sys
import zipfile

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="json" ContentType="application/json"/>'
    '<Default Extension="js" ContentType="application/javascript"/>'
    '<Default Extension="md" ContentType="text/markdown"/>'
    '<Default Extension="txt" ContentType="text/plain"/>'
    '<Default Extension="png" ContentType="image/png"/>'
    '<Default Extension="vsixmanifest" ContentType="text/xml"/>'
    "</Types>"
)

MANIFEST_TPL = """<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{id}" Version="{version}" Publisher="{publisher}"/>
    <DisplayName>{display}</DisplayName>
    <Description xml:space="preserve">{description}</Description>
    <Categories>Other</Categories>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/>
  </Assets>
</PackageManifest>
"""


def esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_manifest(ext_dir: str, pkg: dict) -> str:
    src = os.path.join(ext_dir, ".vsixmanifest")
    if os.path.exists(src):
        with open(src, encoding="utf-8") as f:
            m = f.read()
        return re.sub(
            r'Version="[^"]*"(\s+Publisher=)',
            'Version="%s"\\1' % esc(pkg["version"]),
            m,
            count=1,
        )
    return MANIFEST_TPL.format(
        id=esc(pkg["name"]),
        version=esc(pkg["version"]),
        publisher=esc(pkg.get("publisher", "dao")),
        display=esc(pkg.get("displayName", pkg["name"])),
        description=esc(pkg.get("description", "")),
    )


def pack(ext_dir: str, out_vsix: str) -> None:
    with open(os.path.join(ext_dir, "package.json"), encoding="utf-8") as f:
        pkg = json.load(f)
    with zipfile.ZipFile(out_vsix, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("extension.vsixmanifest", build_manifest(ext_dir, pkg))
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        for root, _dirs, files in os.walk(ext_dir):
            for name in files:
                if name == ".vsixmanifest":
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, ext_dir).replace(os.sep, "/")
                z.write(full, "extension/" + rel)
    print(
        "✓ VSIX: %s (%s.%s@%s)"
        % (out_vsix, pkg.get("publisher", "dao"), pkg["name"], pkg["version"])
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    pack(sys.argv[1], sys.argv[2])
