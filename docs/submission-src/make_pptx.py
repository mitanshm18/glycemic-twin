"""Package rendered slide images into a PowerPoint file (one full-bleed picture per slide).

    python3 docs/submission-src/make_pptx.py OUT.pptx WIDTH_PX HEIGHT_PX slide1.jpg slide2.jpg ...

Standard library only. The PDF next to it is the primary, text-searchable version; this .pptx is
the PowerPoint-compatible copy of the same pages.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

EMU_PER_PX = 6350  # 914400 EMU per inch / 144 px per inch: 1920 px -> 12,192,000 EMU (13.33 in)

NS = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
)
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
EMPTY_TREE = (
    '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
    '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/>'
    '<a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>'
)

THEME = (
    DECL + '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Plain">'
    '<a:themeElements><a:clrScheme name="Plain">'
    '<a:dk1><a:srgbClr val="1B2430"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>'
    '<a:dk2><a:srgbClr val="475262"/></a:dk2><a:lt2><a:srgbClr val="F6F8FA"/></a:lt2>'
    '<a:accent1><a:srgbClr val="2F5FB3"/></a:accent1><a:accent2><a:srgbClr val="6B4FC4"/></a:accent2>'
    '<a:accent3><a:srgbClr val="2F7D55"/></a:accent3><a:accent4><a:srgbClr val="9A6A12"/></a:accent4>'
    '<a:accent5><a:srgbClr val="B8442F"/></a:accent5><a:accent6><a:srgbClr val="6B7684"/></a:accent6>'
    '<a:hlink><a:srgbClr val="2F5FB3"/></a:hlink><a:folHlink><a:srgbClr val="6B4FC4"/></a:folHlink>'
    '</a:clrScheme><a:fontScheme name="Plain"><a:majorFont><a:latin typeface="Arial"/><a:ea typeface=""/>'
    '<a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="Arial"/><a:ea typeface=""/>'
    '<a:cs typeface=""/></a:minorFont></a:fontScheme><a:fmtScheme name="Plain"><a:fillStyleLst>'
    + '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3
    + "</a:fillStyleLst><a:lnStyleLst>"
    + '<a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>' * 3
    + "</a:lnStyleLst><a:effectStyleLst>"
    + "<a:effectStyle><a:effectLst/></a:effectStyle>" * 3
    + "</a:effectStyleLst><a:bgFillStyleLst>"
    + '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>' * 3
    + "</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>"
)


def rels(items: list[tuple[str, str, str]]) -> str:
    body = "".join(f'<Relationship Id="{i}" Type="{t}" Target="{tg}"/>' for i, t, tg in items)
    return DECL + f'<Relationships xmlns="{PKG}">{body}</Relationships>'


def slide_xml(cx: int, cy: int) -> str:
    pic = (
        '<p:pic><p:nvPicPr><p:cNvPr id="2" name="Slide image"/><p:cNvPicPr>'
        '<a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
        '<p:blipFill><a:blip r:embed="rId2"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>'
    )
    tree = EMPTY_TREE.replace("</p:spTree>", pic + "</p:spTree>")
    # a quiet fade between slides; nothing animates inside a slide
    fade = '<p:transition spd="med"><p:fade/></p:transition>'
    return (
        DECL + f"<p:sld {NS}>{tree}<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>{fade}</p:sld>"
    )


def build(out: Path, width_px: int, height_px: int, images: list[Path]) -> None:
    cx, cy = width_px * EMU_PER_PX, height_px * EMU_PER_PX
    n = len(images)
    ct = (
        DECL + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="jpg" ContentType="image/jpeg"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        + "".join(
            f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            for i in range(1, n + 1)
        )
        + "</Types>"
    )
    pres = (
        DECL + f"<p:presentation {NS}>"
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        "<p:sldIdLst>"
        + "".join(f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, n + 1))
        + f'</p:sldIdLst><p:sldSz cx="{cx}" cy="{cy}"/><p:notesSz cx="6858000" cy="9144000"/>'
        "</p:presentation>"
    )
    pres_rels = rels(
        [("rId1", f"{REL}/slideMaster", "slideMasters/slideMaster1.xml")]
        + [(f"rId{i + 1}", f"{REL}/slide", f"slides/slide{i}.xml") for i in range(1, n + 1)]
        + [(f"rId{n + 2}", f"{REL}/theme", "theme/theme1.xml")]
    )
    master = (
        DECL + f"<p:sldMaster {NS}>{EMPTY_TREE}"
        '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
        'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" '
        'folHlink="folHlink"/><p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/>'
        "</p:sldLayoutIdLst></p:sldMaster>"
    )
    layout = (
        DECL
        + f'<p:sldLayout {NS} type="blank" preserve="1">'
        + EMPTY_TREE.replace("<p:cSld>", '<p:cSld name="Blank">')
        + "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>"
    )
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr(
            "_rels/.rels",
            rels([("rId1", f"{REL}/officeDocument", "ppt/presentation.xml")]),
        )
        z.writestr("ppt/presentation.xml", pres)
        z.writestr("ppt/_rels/presentation.xml.rels", pres_rels)
        z.writestr("ppt/slideMasters/slideMaster1.xml", master)
        z.writestr(
            "ppt/slideMasters/_rels/slideMaster1.xml.rels",
            rels(
                [
                    ("rId1", f"{REL}/slideLayout", "../slideLayouts/slideLayout1.xml"),
                    ("rId2", f"{REL}/theme", "../theme/theme1.xml"),
                ]
            ),
        )
        z.writestr("ppt/slideLayouts/slideLayout1.xml", layout)
        z.writestr(
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels",
            rels([("rId1", f"{REL}/slideMaster", "../slideMasters/slideMaster1.xml")]),
        )
        z.writestr("ppt/theme/theme1.xml", THEME)
        for i, img in enumerate(images, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", slide_xml(cx, cy))
            z.writestr(
                f"ppt/slides/_rels/slide{i}.xml.rels",
                rels(
                    [
                        ("rId1", f"{REL}/slideLayout", "../slideLayouts/slideLayout1.xml"),
                        ("rId2", f"{REL}/image", f"../media/image{i}.jpg"),
                    ]
                ),
            )
            z.write(img, f"ppt/media/image{i}.jpg")


if __name__ == "__main__":
    out, w, h, *imgs = sys.argv[1:]
    build(Path(out), int(w), int(h), [Path(p) for p in imgs])
    print(f"wrote {out}: {len(imgs)} slide(s)")
