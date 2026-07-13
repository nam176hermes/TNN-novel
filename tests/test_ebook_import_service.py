from __future__ import annotations

from pathlib import Path
import subprocess
import zipfile

import pytest

from app.database.db import add_book, get_book_by_title, init_db, list_chapters, list_ebook_import_runs
from app.mobile_api.services import ebook_import_service
from app.mobile_api.services.ebook_import_service import EbookImportService, ExistingBookConfirmationRequired


def write_minimal_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Phàm Nhân Tu Tiên</dc:title>
    <dc:creator>Vong Ngữ</dc:creator>
    <dc:language>vi</dc:language>
    <meta name="cover" content="cover-image"/>
  </metadata>
  <manifest>
    <item id="chap1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chap2" href="chapter2.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover-image" href="cover.jpg" media-type="image/jpeg"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
    <itemref idref="chap2"/>
  </spine>
</package>
""",
        )
        epub.writestr(
            "OEBPS/chapter1.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>Chương 1: Sơn biên tiểu thôn</h1>
<p>Hàn Lập khẽ gật đầu.</p>
</body></html>""",
        )
        epub.writestr(
            "OEBPS/chapter2.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>Chương 2: Thanh Ngưu trấn</h1>
<p>Lục ca, ta cảm tạ huynh.</p>
</body></html>""",
        )
        epub.writestr("OEBPS/cover.jpg", b"fake-cover")


def write_inline_image_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Minh Họa Kiếm Hiệp</dc:title>
    <dc:creator>Ẩn Danh</dc:creator>
    <dc:language>vi</dc:language>
    <meta name="cover" content="cover-image"/>
  </metadata>
  <manifest>
    <item id="chap1" href="text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="inline1" href="images/sword-scene.png" media-type="image/png"/>
    <item id="cover-image" href="images/cover.jpg" media-type="image/jpeg"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
        )
        epub.writestr(
            "OEBPS/text/chapter1.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>Chương 1: Kiếm quang</h1>
<p>Kiếm khí nổi lên trước thềm đá.</p>
<img src="../images/sword-scene.png" alt="Kiếm quang trong đêm"/>
<script>alert("bad")</script>
<p>Thiếu niên im lặng thu kiếm.</p>
</body></html>""",
        )
        epub.writestr("OEBPS/images/sword-scene.png", b"fake-inline-image")
        epub.writestr("OEBPS/images/cover.jpg", b"fake-cover-image")


def write_complex_rich_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Rich Reader Test</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="chap1" href="text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chart" href="images/formation.png" media-type="image/png"/>
    <item id="poster" href="images/poster.jpg" media-type="image/jpeg"/>
    <item id="music" href="audio/zither.mp3" media-type="audio/mpeg"/>
    <item id="vision" href="video/vision.mp4" media-type="video/mp4"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
        )
        epub.writestr(
            "OEBPS/text/chapter1.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>Chương 1: Kỳ trận</h1>
<p>Đệ tử bước vào trận.</p>
<figure>
  <img src="../images/formation.png" alt="Trận đồ cổ"/>
  <figcaption>Trận đồ cổ đặt giữa đại điện.</figcaption>
</figure>
<table>
  <caption>Cảnh giới</caption>
  <tbody><tr><th scope="row">Luyện Khí</th><td>Tầng chín</td></tr></tbody>
</table>
<pre>[Đinh!]
Nhiệm vụ mở ra.</pre>
<audio controls="controls" src="../audio/zither.mp3" title="Tiếng đàn cổ"></audio>
<video controls="controls" poster="../images/poster.jpg">
  <source src="../video/vision.mp4" type="video/mp4"/>
</video>
<p>Hắn khép mắt lĩnh ngộ.</p>
</body></html>""",
        )
        epub.writestr("OEBPS/images/formation.png", b"formation-image")
        epub.writestr("OEBPS/images/poster.jpg", b"poster-image")
        epub.writestr("OEBPS/audio/zither.mp3", b"zither-audio")
        epub.writestr("OEBPS/video/vision.mp4", b"vision-video")


def write_responsive_image_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Responsive Image Test</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="chap1" href="text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="small-map" href="images/map-small.webp" media-type="image/webp"/>
    <item id="large-map" href="images/map-large.webp" media-type="image/webp"/>
    <item id="fallback-map" href="images/map.png" media-type="image/png"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
        )
        epub.writestr(
            "OEBPS/text/chapter1.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>Chương 1: Bản đồ bí cảnh</h1>
<p>Hắn mở bản đồ cổ.</p>
<picture>
  <source srcset="../images/map-small.webp 480w, https://tracker.example/bad.webp 640w, data:image/png;base64,AAAA 800w, javascript:alert(1) 900w, ../images/map-large.webp 960w" type="image/webp"/>
  <img src="../images/map.png" alt="Bản đồ bí cảnh"/>
</picture>
</body></html>""",
        )
        epub.writestr("OEBPS/images/map-small.webp", b"small-responsive-map")
        epub.writestr("OEBPS/images/map-large.webp", b"large-responsive-map")
        epub.writestr("OEBPS/images/map.png", b"fallback-responsive-map")


def write_pagination_css_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Pagination CSS</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="chap1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="image1" href="images/mountain.png" media-type="image/png"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
        )
        epub.writestr(
            "OEBPS/chapter1.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><head>
<style>
  .chapter-title { break-before: page; }
  figure.plate { break-inside: avoid; }
  .afterword { page-break-after: always; }
</style>
</head><body>
<h1 class="chapter-title">Chương 1: Vào núi</h1>
<p>Hắn đi qua sơn môn.</p>
<figure class="plate">
  <img src="images/mountain.png" alt="Núi xanh"/>
  <figcaption>Núi xanh</figcaption>
</figure>
<p class="afterword">Hết phần dẫn.</p>
</body></html>""",
        )
        epub.writestr("OEBPS/images/mountain.png", b"mountain-image")


def write_external_pagination_css_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>External Pagination CSS</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="chap1" href="text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="style1" href="styles/book.css" media-type="text/css"/>
    <item id="image1" href="images/mountain.png" media-type="image/png"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
        )
        epub.writestr(
            "OEBPS/text/chapter1.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><head>
<link href="../styles/book.css" rel="stylesheet" type="text/css"/>
</head><body>
<h1 class="chapter-title">Chương 1: Linh sơn</h1>
<p>Hắn đi qua sơn môn.</p>
<figure class="plate">
  <img src="../images/mountain.png" alt="Núi xanh"/>
  <figcaption>Núi xanh</figcaption>
</figure>
<p class="afterword">Hết phần dẫn.</p>
</body></html>""",
        )
        epub.writestr(
            "OEBPS/styles/book.css",
            """
.chapter-title { break-before: page; }
figure.plate { break-inside: avoid; }
.afterword { page-break-after: always; }
""",
        )
        epub.writestr("OEBPS/images/mountain.png", b"mountain-image")


def write_imported_pagination_css_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Imported Pagination CSS</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="chap1" href="text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="style1" href="styles/book.css" media-type="text/css"/>
    <item id="style2" href="styles/pagination.css" media-type="text/css"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
        )
        epub.writestr(
            "OEBPS/text/chapter1.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><head>
<link href="../styles/book.css" rel="stylesheet" type="text/css"/>
</head><body>
<h1 class="chapter-title">Chương 1: Mật cảnh</h1>
<p>Hắn bước qua cửa đá.</p>
<figure class="plate">
  <img src="../images/mountain.png" alt="Mật cảnh"/>
  <figcaption>Mật cảnh</figcaption>
</figure>
<p class="afterword">Hết phần dẫn.</p>
</body></html>""",
        )
        epub.writestr("OEBPS/styles/book.css", '@import "pagination.css";\nbody { margin: 0; }')
        epub.writestr(
            "OEBPS/styles/pagination.css",
            """
.chapter-title { break-before: page; }
figure.plate { break-inside: avoid; }
.afterword { page-break-after: always; }
""",
        )


def write_paragraph_spacing_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Độc Tu Paragraphs</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="chap1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
        )
        epub.writestr(
            "OEBPS/chapter1.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h1>Chương 1: Lý Thị!</h1>
<p>Hắc sơn.</p>
<p>Thần Mộc thành.</p>
<p>Trong thành có một tu tiên đại tộc tên là Lý thị.</p>
</body></html>""",
        )


def write_toc_short_spine_rich_epub(path: Path, count: int = 6) -> None:
    nav_items = "\n".join(
        f'<li><a href="short/{index}.xhtml">Chương {index}: Tiêu đề {index}</a></li>'
        for index in range(1, count + 1)
    )
    manifest_items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="deco" href="images/deco.png" media-type="image/png"/>',
    ]
    spine_items: list[str] = []
    for index in range(1, count + 1):
        manifest_items.append(
            f'<item id="short{index}" href="short/{index}.xhtml" media-type="application/xhtml+xml"/>'
        )
        manifest_items.append(
            f'<item id="body{index}" href="body/{index}.xhtml" media-type="application/xhtml+xml"/>'
        )
        spine_items.append(f'<itemref idref="body{index}"/>')

    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            f"""<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>TOC Lỗi</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>{''.join(manifest_items)}</manifest>
  <spine>{''.join(spine_items)}</spine>
</package>""",
        )
        epub.writestr(
            "OEBPS/nav.xhtml",
            f"""<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol>
{nav_items}
</ol></nav></body></html>""",
        )
        for index in range(1, count + 1):
            epub.writestr(
                f"OEBPS/short/{index}.xhtml",
                f"""<html><body>
<h1>Chương {index}: Tiêu đề {index}</h1>
<p><img src="../images/deco.png" alt="Minh họa"/></p>
</body></html>""",
            )
            epub.writestr(
                f"OEBPS/body/{index}.xhtml",
                f"""<html><body>
<h1>Chương {index}: Nội dung {index}</h1>
<p>Đây là phần thân chương {index}, có đủ chữ để đọc và nhập vào thư viện.</p>
</body></html>""",
            )
        epub.writestr("OEBPS/images/deco.png", b"fake-deco")


def write_image_only_chapter_epub(path: Path, count: int = 6) -> None:
    manifest_items = ['<item id="deco" href="images/deco.png" media-type="image/png"/>']
    spine_items: list[str] = []
    for index in range(1, count + 1):
        manifest_items.append(
            f'<item id="chap{index}" href="chapter{index}.xhtml" media-type="application/xhtml+xml"/>'
        )
        spine_items.append(f'<itemref idref="chap{index}"/>')

    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            f"""<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Ảnh Không Chữ</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>{''.join(manifest_items)}</manifest>
  <spine>{''.join(spine_items)}</spine>
</package>""",
        )
        for index in range(1, count + 1):
            epub.writestr(
                f"OEBPS/chapter{index}.xhtml",
                f"""<html><body>
<h1>Chương {index}: Tên chương {index}</h1>
<p><img src="images/deco.png" alt="Minh họa"/></p>
</body></html>""",
            )
        epub.writestr("OEBPS/images/deco.png", b"fake-deco")


def write_heading_split_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Toàn Bản Dịch</dc:title>
    <dc:creator>Dịch giả</dc:creator>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="body" href="body.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="body"/></spine>
</package>""",
        )
        epub.writestr(
            "OEBPS/body.xhtml",
            """<html><body>
<h1>Chương 1: Khai cục</h1><p>Hắn mở mắt giữa động phủ.</p>
<h1>Chương 2: Linh thạch</h1><p>Một viên linh thạch rơi xuống.</p>
</body></html>""",
        )


def write_epub2_ncx_no_heading_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Toc NCX Book</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx"><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>""",
        )
        epub.writestr(
            "OEBPS/toc.ncx",
            """<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
  <navMap>
    <navPoint id="nav-1" playOrder="1"><navLabel><text>Chương 1: Gió nổi</text></navLabel><content src="c1.xhtml"/></navPoint>
    <navPoint id="nav-2" playOrder="2"><navLabel><text>Chương 2: Mưa về</text></navLabel><content src="c2.xhtml"/></navPoint>
  </navMap>
</ncx>""",
        )
        epub.writestr("OEBPS/c1.xhtml", "<html><body><p>Thiếu niên đứng trước sơn môn.</p></body></html>")
        epub.writestr("OEBPS/c2.xhtml", "<html><body><p>Trời đổ mưa trên Thanh Ngưu trấn.</p></body></html>")


def write_epub3_nav_no_heading_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Toc Nav Book</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="chapters/one.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="chapters/two.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>""",
        )
        epub.writestr(
            "OEBPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <body><nav epub:type="toc"><ol>
    <li><a href="chapters/one.xhtml">第十二章 雪夜来客</a></li>
    <li><a href="chapters/two.xhtml">第十三章 风雪归人</a></li>
  </ol></nav></body>
</html>""",
        )
        epub.writestr("OEBPS/chapters/one.xhtml", "<html><body><p>Tuyết phủ kín sân viện.</p></body></html>")
        epub.writestr("OEBPS/chapters/two.xhtml", "<html><body><p>Người cũ trở về giữa gió tuyết.</p></body></html>")


def write_anchor_toc_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Anchor Book</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="body" href="body.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="body"/></spine>
</package>""",
        )
        epub.writestr(
            "OEBPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol>
  <li><a href="body.xhtml#c1">Chapter 1: Cave</a></li>
  <li><a href="body.xhtml#c2">Chapter 2: Sword</a></li>
</ol></nav></body></html>""",
        )
        epub.writestr(
            "OEBPS/body.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
<h2 id="c1">Cave</h2><p>Hắn tỉnh lại trong động phủ.</p>
<h2 id="c2">Sword</h2><p>Kiếm quang lóe lên trong đêm.</p>
</body></html>""",
        )


def write_toc_with_garbage_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Toc Garbage Book</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
    <item id="c1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="copyright" href="copyright.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="cover"/><itemref idref="c1"/><itemref idref="copyright"/></spine>
</package>""",
        )
        epub.writestr(
            "OEBPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol>
  <li><a href="cover.xhtml">Cover</a></li>
  <li><a href="chapter1.xhtml">Chương 1: Chính văn</a></li>
  <li><a href="copyright.xhtml">Copyright</a></li>
</ol></nav></body></html>""",
        )
        epub.writestr("OEBPS/cover.xhtml", "<html><body><p>Cover page</p></body></html>")
        epub.writestr("OEBPS/chapter1.xhtml", "<html><body><p>Đây là chính văn của truyện.</p></body></html>")
        epub.writestr("OEBPS/copyright.xhtml", "<html><body><p>Copyright page</p></body></html>")


def write_toc_generic_labels_with_embedded_headings_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Độc Tu</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="c1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="chapter2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>""",
        )
        epub.writestr(
            "OEBPS/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol>
  <li><a href="chapter1.xhtml">Giới thiệu</a></li>
  <li><a href="chapter2.xhtml">Mục lục</a></li>
</ol></nav></body></html>""",
        )
        epub.writestr(
            "OEBPS/chapter1.xhtml",
            """<html><body>
<p>Độc Tu - Dịch Full</p>
<p>Chương 1: Lý Thị!</p>
<p>Hắc sơn.</p>
</body></html>""",
        )
        epub.writestr(
            "OEBPS/chapter2.xhtml",
            """<html><body>
<p>Độc Tu - Dịch Full</p>
<p>Chương 2: Năm Loại Đồng Tham!</p>
<p>Các ngươi phải hiểu rằng, nơi nào có người, ở đó có tranh đấu.</p>
</body></html>""",
        )


def write_many_chapter_epub(path: Path, count: int = 45) -> None:
    manifest_items = "\n".join(
        f'<item id="chap{i}" href="chapter{i}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(1, count + 1)
    )
    spine_items = "\n".join(f'<itemref idref="chap{i}"/>' for i in range(1, count + 1))
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            f"""<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Trường Thiên Lục</dc:title>
    <dc:creator>Tác giả</dc:creator>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>{manifest_items}</manifest>
  <spine>{spine_items}</spine>
</package>""",
        )
        for index in range(1, count + 1):
            epub.writestr(
                f"OEBPS/chapter{index}.xhtml",
                f"<html><body><h1>Chương {index}: Hồi {index}</h1><p>Nội dung chương {index} đủ dài để xem trước.</p></body></html>",
            )


def write_missing_title_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:creator>Không rõ</dc:creator>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>""",
        )
        epub.writestr(
            "OEBPS/c1.xhtml",
            "<html><body><h1>Chương 1: Vào núi</h1><p>Thiếu niên bước vào núi.</p></body></html>",
        )


def write_calibre_garbage_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            """<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Calibre Rác</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    <item id="titlepage" href="titlepage.xhtml" media-type="application/xhtml+xml"/>
    <item id="part0000" href="part0000.xhtml" media-type="application/xhtml+xml"/>
    <item id="c1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="titlepage"/>
    <itemref idref="part0000"/>
    <itemref idref="c1"/>
  </spine>
</package>""",
        )
        epub.writestr("OEBPS/titlepage.xhtml", "<html><body><p>Cover</p></body></html>")
        epub.writestr("OEBPS/part0000.xhtml", "<html><body><p>Ngắn.</p></body></html>")
        epub.writestr(
            "OEBPS/chapter1.xhtml",
            "<html><body><h1>Chương 1: Chính văn</h1><p>Đây là nội dung chính của truyện.</p></body></html>",
        )


def write_named_garbage_epub(path: Path) -> None:
    garbage_ids = ["cover", "toc", "copyright", "about"]
    manifest_items = "\n".join(
        f'<item id="{item}" href="{item}.xhtml" media-type="application/xhtml+xml"/>'
        for item in garbage_ids
    )
    spine_items = "\n".join(f'<itemref idref="{item}"/>' for item in garbage_ids)
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
</container>""",
        )
        epub.writestr(
            "OEBPS/content.opf",
            f"""<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Named Garbage</dc:title>
    <dc:language>vi</dc:language>
  </metadata>
  <manifest>
    {manifest_items}
    <item id="c1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    {spine_items}
    <itemref idref="c1"/>
  </spine>
</package>""",
        )
        for item in garbage_ids:
            epub.writestr(f"OEBPS/{item}.xhtml", f"<html><body><p>{item}</p></body></html>")
        epub.writestr(
            "OEBPS/chapter1.xhtml",
            "<html><body><h1>Chương 1: Chính văn</h1><p>Đây là chương chính sau các trang phụ.</p></body></html>",
        )


def test_epub_preview_reads_metadata_spine_chapters_and_cover(tmp_path: Path, temp_db_path: Path) -> None:
    epub_path = tmp_path / "translated.epub"
    write_minimal_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    preview = service.preview(epub_path)

    assert preview["title"] == "Phàm Nhân Tu Tiên"
    assert preview["author"] == "Vong Ngữ"
    assert preview["language"] == "vi"
    assert preview["source_format"] == "epub"
    assert preview["cover_present"] is True
    assert preview["cover_preview_url"].startswith("/covers/previews/")
    cover_preview_path = tmp_path / "data" / "covers" / preview["cover_preview_url"].removeprefix("/covers/")
    assert cover_preview_path.read_bytes() == b"fake-cover"
    assert preview["chapter_count"] == 2
    assert preview["chapters"][0] == {
        "chapter_number": 1,
        "title": "Sơn biên tiểu thôn",
        "sample": "Hàn Lập khẽ gật đầu.",
    }
    assert preview["chapters"][1]["title"] == "Thanh Ngưu trấn"


def test_epub2_ncx_toc_splits_chapters_without_heading_text(tmp_path: Path, temp_db_path: Path) -> None:
    epub_path = tmp_path / "toc-ncx.epub"
    write_epub2_ncx_no_heading_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    preview = service.preview(epub_path)

    assert preview["split_method"] == "toc"
    assert preview["toc_chapter_count"] == 2
    assert preview["chapter_count"] == 2
    assert preview["chapters"][0] == {
        "chapter_number": 1,
        "title": "Gió nổi",
        "sample": "Thiếu niên đứng trước sơn môn.",
    }
    assert preview["chapters"][1]["title"] == "Mưa về"


def test_epub3_nav_toc_splits_chapters_without_heading_text(tmp_path: Path, temp_db_path: Path) -> None:
    epub_path = tmp_path / "toc-nav.epub"
    write_epub3_nav_no_heading_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    preview = service.preview(epub_path)

    assert preview["split_method"] == "toc"
    assert preview["toc_chapter_count"] == 2
    assert [chapter["chapter_number"] for chapter in preview["chapters"]] == [12, 13]
    assert [chapter["title"] for chapter in preview["chapters"]] == ["雪夜来客", "风雪归人"]
    assert preview["chapters"][0]["sample"] == "Tuyết phủ kín sân viện."


def test_toc_anchor_entries_split_multiple_chapters_inside_one_xhtml(tmp_path: Path, temp_db_path: Path) -> None:
    epub_path = tmp_path / "anchor-toc.epub"
    write_anchor_toc_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    result = service.import_translated_ebook(epub_path, duplicate_strategy="error")

    book = get_book_by_title(temp_db_path, "Anchor Book")
    assert book is not None
    chapters = sorted(list_chapters(temp_db_path, book["id"]), key=lambda item: item["chapter_number"])
    assert result["chapter_count"] == 2
    assert [chapter["title"] for chapter in chapters] == ["Cave", "Sword"]
    assert Path(chapters[0]["translated_text_path"]).read_text(encoding="utf-8") == "Cave\nHắn tỉnh lại trong động phủ."
    assert Path(chapters[1]["translated_text_path"]).read_text(encoding="utf-8") == "Sword\nKiếm quang lóe lên trong đêm."


def test_toc_split_filters_garbage_entries_and_warns(tmp_path: Path, temp_db_path: Path) -> None:
    epub_path = tmp_path / "toc-garbage.epub"
    write_toc_with_garbage_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    preview = service.preview(epub_path)

    assert preview["split_method"] == "toc"
    assert preview["toc_chapter_count"] == 1
    assert preview["chapter_count"] == 1
    assert preview["chapters"][0]["title"] == "Chính văn"
    warning_messages = "\n".join(warning["message"] for warning in preview["warnings"])
    assert "Cover" in warning_messages
    assert "Copyright" in warning_messages


def test_toc_split_uses_embedded_chapter_heading_when_toc_label_is_generic(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "generic-toc-labels.epub"
    write_toc_generic_labels_with_embedded_headings_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    result = service.import_translated_ebook(epub_path, duplicate_strategy="error")

    chapters = sorted(list_chapters(temp_db_path, result["book_id"]), key=lambda item: item["chapter_number"])
    assert [chapter["chapter_number"] for chapter in chapters] == [1, 2]
    assert [chapter["title"] for chapter in chapters] == ["Lý Thị!", "Năm Loại Đồng Tham!"]
    assert Path(chapters[0]["translated_text_path"]).read_text(encoding="utf-8") == "Hắc sơn."
    assert Path(chapters[1]["translated_text_path"]).read_text(encoding="utf-8").startswith("Các ngươi phải hiểu")


def test_epub_preview_returns_first_and_last_twenty_chapters(tmp_path: Path, temp_db_path: Path) -> None:
    epub_path = tmp_path / "many.epub"
    write_many_chapter_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    preview = service.preview(epub_path)

    assert preview["chapter_count"] == 45
    assert len(preview["first_chapters"]) == 20
    assert len(preview["last_chapters"]) == 20
    assert preview["first_chapters"][0]["chapter_number"] == 1
    assert preview["first_chapters"][-1]["chapter_number"] == 20
    assert preview["last_chapters"][0]["chapter_number"] == 26
    assert preview["last_chapters"][-1]["chapter_number"] == 45
    assert preview["chapters"][0]["chapter_number"] == 1
    assert preview["chapters"][-1]["chapter_number"] == 45


def test_epub_preview_uses_original_filename_when_metadata_title_is_missing(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    epub_path = tmp_path / "upload-temp.epub"
    write_missing_title_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    preview = service.preview(epub_path, original_filename="Thanh Sơn bản dịch.epub")

    assert preview["title"] == "Thanh Sơn bản dịch"


def test_epub_preview_warns_and_filters_calibre_garbage(tmp_path: Path, temp_db_path: Path) -> None:
    epub_path = tmp_path / "garbage.epub"
    write_calibre_garbage_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    preview = service.preview(epub_path)

    warning_types = {warning["type"] for warning in preview["warnings"]}
    warning_messages = "\n".join(warning["message"] for warning in preview["warnings"])
    assert preview["chapter_count"] == 1
    assert all(chapter["title"] != "titlepage" for chapter in preview["chapters"])
    assert "filtered_garbage" in warning_types
    assert "suspect_chapter" in warning_types
    assert "short_chapter" in warning_types
    assert "titlepage" in warning_messages
    assert "part0000" in warning_messages


def test_epub_preview_filters_named_garbage_documents(tmp_path: Path, temp_db_path: Path) -> None:
    epub_path = tmp_path / "named-garbage.epub"
    write_named_garbage_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    preview = service.preview(epub_path)

    warning_messages = "\n".join(warning["message"] for warning in preview["warnings"])
    assert preview["chapter_count"] == 1
    assert preview["chapters"][0]["title"] == "Chính văn"
    for marker in ["cover", "toc", "copyright", "about"]:
        assert marker in warning_messages


def test_import_translated_epub_writes_translated_chapters_to_library(tmp_path: Path, temp_db_path: Path) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "translated.epub"
    write_minimal_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    result = service.import_translated_ebook(epub_path, duplicate_strategy="error")

    book = get_book_by_title(temp_db_path, "Phàm Nhân Tu Tiên")
    assert book is not None
    assert book["id"] == result["book_id"]
    assert book["author"] == "Vong Ngữ"
    assert book["source"] == "ebook"
    chapters = sorted(list_chapters(temp_db_path, book["id"]), key=lambda item: item["chapter_number"])
    assert result["imported_chapters"] == 2
    assert result["skipped_chapters"] == 0
    assert result["cover_url"].startswith("/covers/")
    assert book["cover_path"]
    assert Path(book["cover_path"]).read_bytes() == b"fake-cover"
    assert [chapter["status"] for chapter in chapters] == ["translated", "translated"]
    assert [chapter["title"] for chapter in chapters] == ["Sơn biên tiểu thôn", "Thanh Ngưu trấn"]
    assert chapters[0]["raw_text_path"]
    assert Path(chapters[0]["raw_text_path"]).read_text(encoding="utf-8") == "Hàn Lập khẽ gật đầu."
    assert Path(chapters[0]["translated_text_path"]).read_text(encoding="utf-8") == "Hàn Lập khẽ gật đầu."
    assert Path(chapters[1]["translated_text_path"]).read_text(encoding="utf-8") == "Lục ca, ta cảm tạ huynh."


def test_import_translated_epub_preserves_paragraph_spacing_in_text_files(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "paragraphs.epub"
    write_paragraph_spacing_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    result = service.import_translated_ebook(epub_path, duplicate_strategy="error")

    chapters = list_chapters(temp_db_path, result["book_id"])
    imported_text = Path(chapters[0]["translated_text_path"]).read_text(encoding="utf-8")
    assert imported_text == (
        "Hắc sơn.\n\n"
        "Thần Mộc thành.\n\n"
        "Trong thành có một tu tiên đại tộc tên là Lý thị."
    )


def test_import_translated_txt_splits_vietnamese_chapter_headings(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    txt_path = tmp_path / "Thanh Sơn bản dịch.txt"
    txt_path.write_text(
        """Chương 1: Gió nổi
Thiếu niên áo xanh đứng trước sơn môn.

Chương 2 - Kiếm ý
Một luồng kiếm khí lạnh thấu xương vụt qua.

Phiên ngoại: Cố nhân
Năm xưa cố nhân trở lại dưới chân núi.
""",
        encoding="utf-8",
    )
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    preview = service.preview(txt_path, original_filename=txt_path.name)
    result = service.import_translated_ebook(txt_path, duplicate_strategy="error", original_filename=txt_path.name)

    book = get_book_by_title(temp_db_path, "Thanh Sơn bản dịch")
    assert book is not None
    chapters = sorted(list_chapters(temp_db_path, book["id"]), key=lambda item: item["chapter_number"])
    assert preview["source_format"] == "txt"
    assert preview["split_method"] == "regex"
    assert preview["chapter_count"] == 3
    assert preview["chapters"][2]["title"] == "Phiên ngoại: Cố nhân"
    assert any(warning["type"] == "regex_chapter_detection" for warning in preview["warnings"])
    assert result["imported_chapters"] == 3
    assert [chapter["chapter_number"] for chapter in chapters] == [1, 2, 3]
    assert [chapter["title"] for chapter in chapters] == ["Gió nổi", "Kiếm ý", "Phiên ngoại: Cố nhân"]
    assert Path(chapters[2]["translated_text_path"]).read_text(encoding="utf-8") == (
        "Năm xưa cố nhân trở lại dưới chân núi."
    )


def test_translated_txt_keeps_prologue_without_duplicate_chapter_numbers(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    txt_path = tmp_path / "Linh Sơn.txt"
    txt_path.write_text(
        """Mở đầu
Đêm ấy, chuông cổ ngân vang khắp Linh Sơn.

Chương 1: Nhập môn
Thiếu niên bước lên bậc đá đầu tiên.
""",
        encoding="utf-8",
    )
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    result = service.import_translated_ebook(txt_path, duplicate_strategy="error", original_filename=txt_path.name)

    chapters = sorted(list_chapters(temp_db_path, result["book_id"]), key=lambda item: item["chapter_number"])
    assert [chapter["chapter_number"] for chapter in chapters] == [1, 2]
    assert [chapter["title"] for chapter in chapters] == ["Mở đầu", "Nhập môn"]


def test_import_translated_html_splits_headings_and_ignores_scripts(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    html_path = tmp_path / "Kiếm Vực.html"
    html_path.write_text(
        """<html><body>
<h1>Chương 1: Kiếm minh</h1>
<p>Kiếm khí ngân vang trong màn mưa.</p>
<script>Không được nhập đoạn này.</script>
<h1>Chương 2: Sơn môn</h1>
<p>Đệ tử áo trắng cúi đầu hành lễ.</p>
</body></html>""",
        encoding="utf-8",
    )
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    result = service.import_translated_ebook(html_path, duplicate_strategy="error", original_filename=html_path.name)

    chapters = sorted(list_chapters(temp_db_path, result["book_id"]), key=lambda item: item["chapter_number"])
    assert result["source_format"] == "html"
    assert result["split_method"] == "regex"
    assert [chapter["title"] for chapter in chapters] == ["Kiếm minh", "Sơn môn"]
    first_text = Path(chapters[0]["translated_text_path"]).read_text(encoding="utf-8")
    assert first_text == "Kiếm khí ngân vang trong màn mưa."
    assert "Không được nhập đoạn này" not in first_text


def test_import_translated_epub_preserves_inline_images_as_chapter_html(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "illustrated.epub"
    write_inline_image_epub(epub_path)
    data_dir = tmp_path / "data"
    service = EbookImportService(db_path=temp_db_path, data_dir=data_dir)

    result = service.import_translated_ebook(epub_path, duplicate_strategy="error")

    book = get_book_by_title(temp_db_path, "Minh Họa Kiếm Hiệp")
    assert book is not None
    assert book["id"] == result["book_id"]
    assert Path(book["cover_path"]).read_bytes() == b"fake-cover-image"
    chapters = list_chapters(temp_db_path, book["id"])
    assert len(chapters) == 1
    chapter = chapters[0]
    assert Path(chapter["translated_text_path"]).read_text(encoding="utf-8") == (
        "Kiếm khí nổi lên trước thềm đá.\n\nThiếu niên im lặng thu kiếm."
    )
    html_path = Path(chapter["content_html_path"])
    html = html_path.read_text(encoding="utf-8")
    assert "/book-assets/" in html
    assert "sword-scene.png" in html
    assert "<script" not in html
    assert "fake-inline-image" not in html

    copied_images = list((data_dir / "book_assets" / str(book["id"])).glob("*.png"))
    assert len(copied_images) == 1
    assert copied_images[0].read_bytes() == b"fake-inline-image"


def test_import_translated_epub_preserves_complex_rich_html_and_media_assets(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "complex-rich.epub"
    write_complex_rich_epub(epub_path)
    data_dir = tmp_path / "data"
    service = EbookImportService(db_path=temp_db_path, data_dir=data_dir)

    result = service.import_translated_ebook(epub_path, duplicate_strategy="error")

    book = get_book_by_title(temp_db_path, "Rich Reader Test")
    assert book is not None
    chapter = list_chapters(temp_db_path, book["id"])[0]
    html = Path(chapter["content_html_path"]).read_text(encoding="utf-8")
    assert result["book_id"] == book["id"]
    assert "<figure>" in html
    assert "<figcaption>Trận đồ cổ đặt giữa đại điện.</figcaption>" in html
    assert "<table>" in html
    assert "<caption>Cảnh giới</caption>" in html
    assert "<th scope=\"row\">Luyện Khí</th>" in html
    assert "<pre>[Đinh!]\nNhiệm vụ mở ra.</pre>" in html
    assert "<audio controls=\"controls\"" in html
    assert "<video controls=\"controls\"" in html
    assert "<source src=\"/book-assets/" in html
    assert "formation.png" in html
    assert "poster.jpg" in html
    assert "zither.mp3" in html
    assert "vision.mp4" in html

    asset_dir = data_dir / "book_assets" / str(book["id"])
    copied_assets = {path.name: path.read_bytes() for path in asset_dir.iterdir()}
    assert any(name.endswith("formation.png") and content == b"formation-image" for name, content in copied_assets.items())
    assert any(name.endswith("poster.jpg") and content == b"poster-image" for name, content in copied_assets.items())
    assert any(name.endswith("zither.mp3") and content == b"zither-audio" for name, content in copied_assets.items())
    assert any(name.endswith("vision.mp4") and content == b"vision-video" for name, content in copied_assets.items())


def test_import_translated_epub_rewrites_source_srcset_assets(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "responsive-image.epub"
    write_responsive_image_epub(epub_path)
    data_dir = tmp_path / "data"
    service = EbookImportService(db_path=temp_db_path, data_dir=data_dir)

    service.import_translated_ebook(epub_path, duplicate_strategy="error")

    book = get_book_by_title(temp_db_path, "Responsive Image Test")
    assert book is not None
    chapter = list_chapters(temp_db_path, book["id"])[0]
    html = Path(chapter["content_html_path"]).read_text(encoding="utf-8")
    assert 'srcset="/book-assets/' in html
    assert "map-small.webp 480w" in html
    assert "map-large.webp 960w" in html
    assert 'src="/book-assets/' in html
    assert "../images/map-small.webp" not in html
    assert "../images/map-large.webp" not in html
    assert "../images/map.png" not in html
    assert "tracker.example" not in html
    assert "data:image" not in html
    assert "javascript:" not in html

    asset_dir = data_dir / "book_assets" / str(book["id"])
    copied_assets = {path.name: path.read_bytes() for path in asset_dir.iterdir()}
    assert any(name.endswith("map-small.webp") and content == b"small-responsive-map" for name, content in copied_assets.items())
    assert any(name.endswith("map-large.webp") and content == b"large-responsive-map" for name, content in copied_assets.items())
    assert any(name.endswith("map.png") and content == b"fallback-responsive-map" for name, content in copied_assets.items())


def test_import_translated_epub_bakes_stylesheet_pagination_hints_into_html(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "pagination-css.epub"
    write_pagination_css_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    service.import_translated_ebook(epub_path, duplicate_strategy="error")

    book = get_book_by_title(temp_db_path, "Pagination CSS")
    assert book is not None
    chapter = list_chapters(temp_db_path, book["id"])[0]
    html = Path(chapter["content_html_path"]).read_text(encoding="utf-8")
    assert "<style>" not in html
    assert "class=" not in html
    assert '<h1 data-page-break-before="always">Chương 1: Vào núi</h1>' in html
    assert '<figure data-page-break-inside="avoid">' in html
    assert '<p data-page-break-after="always">Hết phần dẫn.</p>' in html


def test_import_translated_epub_bakes_external_stylesheet_pagination_hints_into_html(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "external-pagination-css.epub"
    write_external_pagination_css_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    service.import_translated_ebook(epub_path, duplicate_strategy="error")

    book = get_book_by_title(temp_db_path, "External Pagination CSS")
    assert book is not None
    chapter = list_chapters(temp_db_path, book["id"])[0]
    html = Path(chapter["content_html_path"]).read_text(encoding="utf-8")
    assert "<link" not in html
    assert "class=" not in html
    assert '<h1 data-page-break-before="always">Chương 1: Linh sơn</h1>' in html
    assert '<figure data-page-break-inside="avoid">' in html
    assert '<p data-page-break-after="always">Hết phần dẫn.</p>' in html


def test_import_translated_epub_follows_imported_stylesheet_pagination_hints(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "imported-pagination-css.epub"
    write_imported_pagination_css_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    service.import_translated_ebook(epub_path, duplicate_strategy="error")

    book = get_book_by_title(temp_db_path, "Imported Pagination CSS")
    assert book is not None
    chapter = list_chapters(temp_db_path, book["id"])[0]
    html = Path(chapter["content_html_path"]).read_text(encoding="utf-8")
    assert '<h1 data-page-break-before="always">Chương 1: Mật cảnh</h1>' in html
    assert '<figure data-page-break-inside="avoid">' in html
    assert '<p data-page-break-after="always">Hết phần dẫn.</p>' in html


def test_epub_preview_falls_back_to_spine_when_toc_chapters_are_title_only(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    epub_path = tmp_path / "bad-toc-good-spine.epub"
    write_toc_short_spine_rich_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    preview = service.preview(epub_path)

    assert preview["split_method"] == "spine"
    assert preview["toc_chapter_count"] == 6
    assert preview["chapter_count"] == 6
    assert preview["chapters"][0]["title"] == "Nội dung 1"
    assert "phần thân chương 1" in preview["chapters"][0]["sample"]
    assert any(warning["type"] == "toc_low_quality_fallback" for warning in preview["warnings"])


def test_image_only_epub_preview_warns_and_import_rejects_unreadable_chapters(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "image-only.epub"
    write_image_only_chapter_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    preview = service.preview(epub_path)

    assert preview["chapter_count"] == 6
    assert any(warning["type"] == "unreadable_ebook" for warning in preview["warnings"])
    try:
        service.import_translated_ebook(epub_path, duplicate_strategy="error")
    except ValueError as exc:
        assert "không có nội dung chữ" in str(exc)
    else:
        raise AssertionError("Expected image-only ebook import to be rejected")


def test_preview_reports_automatic_existing_book_match(tmp_path: Path, temp_db_path: Path) -> None:
    init_db(temp_db_path)
    ebook = tmp_path / "translated.epub"
    write_minimal_epub(ebook)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")
    first = service.import_translated_ebook(ebook, duplicate_strategy="error")

    dry_run = service.preview(ebook)["dry_run"]

    assert dry_run["existing_book_id"] == first["book_id"]
    assert dry_run["existing_book_title"] == "Phàm Nhân Tu Tiên"
    assert dry_run["existing_chapter_count"] == 2
    assert dry_run["book_match_reason"] == "title"
    assert dry_run["requires_existing_book_confirmation"] is True


def test_preview_reports_new_and_explicit_target_matches(tmp_path: Path, temp_db_path: Path) -> None:
    init_db(temp_db_path)
    ebook = tmp_path / "translated.epub"
    write_minimal_epub(ebook)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    fresh = service.preview(ebook)["dry_run"]
    assert fresh["book_match_reason"] == "new"
    assert fresh["requires_existing_book_confirmation"] is False

    existing_id = add_book(temp_db_path, "Truyện đích", "", "ebook", "")
    selected = service.preview(ebook, target_book_id=existing_id)["dry_run"]
    assert selected["existing_book_id"] == existing_id
    assert selected["existing_chapter_count"] == 0
    assert selected["book_match_reason"] == "selected"
    assert selected["requires_existing_book_confirmation"] is True


def test_existing_book_import_requires_exact_confirmation_before_mutation(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    ebook = tmp_path / "translated.epub"
    write_minimal_epub(ebook)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")
    first = service.import_translated_ebook(ebook, duplicate_strategy="error")
    before_raw = sorted((tmp_path / "data" / "raw").glob("*"))
    before_runs = list_ebook_import_runs(temp_db_path)

    with pytest.raises(ExistingBookConfirmationRequired):
        service.import_translated_ebook(ebook, duplicate_strategy="skip")
    with pytest.raises(ExistingBookConfirmationRequired):
        service.import_translated_ebook(
            ebook,
            duplicate_strategy="skip",
            confirmed_existing_book_id=first["book_id"] + 1,
        )

    assert sorted((tmp_path / "data" / "raw").glob("*")) == before_raw
    assert list_ebook_import_runs(temp_db_path) == before_runs


def test_exact_existing_book_confirmation_preserves_duplicate_strategy(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    ebook = tmp_path / "translated.epub"
    write_minimal_epub(ebook)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")
    first = service.import_translated_ebook(ebook, duplicate_strategy="error")

    second = service.import_translated_ebook(
        ebook,
        duplicate_strategy="skip",
        confirmed_existing_book_id=first["book_id"],
    )

    assert second["imported_chapters"] == 0
    assert second["skipped_chapters"] == 2


def test_epub_preview_includes_dry_run_counts_for_duplicates(tmp_path: Path, temp_db_path: Path) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "translated.epub"
    write_minimal_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")
    service.import_translated_ebook(epub_path, duplicate_strategy="error")

    skip_preview = service.preview(epub_path)
    overwrite_preview = service.preview(epub_path, duplicate_strategy="overwrite")

    assert skip_preview["dry_run"] == {
        "target_book_id": get_book_by_title(temp_db_path, "Phàm Nhân Tu Tiên")["id"],
        "target_title": "Phàm Nhân Tu Tiên",
        "duplicate_strategy": "skip",
        "chapter_count": 2,
        "new_chapters": 0,
        "duplicate_chapters": 2,
        "would_import": 0,
        "would_skip": 2,
        "would_overwrite": 0,
        "would_error": 0,
        "existing_book_id": get_book_by_title(temp_db_path, "Phàm Nhân Tu Tiên")["id"],
        "existing_book_title": "Phàm Nhân Tu Tiên",
        "existing_chapter_count": 2,
        "book_match_reason": "title",
        "requires_existing_book_confirmation": True,
    }
    assert overwrite_preview["dry_run"]["would_import"] == 2
    assert overwrite_preview["dry_run"]["would_overwrite"] == 2


def test_import_translated_epub_records_import_history(tmp_path: Path, temp_db_path: Path) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "translated.epub"
    write_minimal_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    result = service.import_translated_ebook(
        epub_path,
        duplicate_strategy="skip",
        original_filename="pham-nhan.epub",
    )

    history = list_ebook_import_runs(temp_db_path)
    assert len(history) == 1
    assert history[0]["book_id"] == result["book_id"]
    assert history[0]["filename"] == "pham-nhan.epub"
    assert history[0]["imported_chapters"] == 2
    assert history[0]["skipped_chapters"] == 0


def test_import_translated_epub_defaults_to_skipping_duplicate_chapters(
    tmp_path: Path,
    temp_db_path: Path,
) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "translated.epub"
    write_minimal_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    first = service.import_translated_ebook(epub_path, duplicate_strategy="error")
    second = service.import_translated_ebook(
        epub_path,
        confirmed_existing_book_id=first["book_id"],
    )

    assert first["imported_chapters"] == 2
    assert second["imported_chapters"] == 0
    assert second["skipped_chapters"] == 2
    book = get_book_by_title(temp_db_path, "Phàm Nhân Tu Tiên")
    assert book is not None
    assert len(list_chapters(temp_db_path, book["id"])) == 2


def test_single_split_mode_imports_whole_ebook_as_one_translated_chapter(tmp_path: Path, temp_db_path: Path) -> None:
    init_db(temp_db_path)
    epub_path = tmp_path / "heading-split.epub"
    write_heading_split_epub(epub_path)
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")

    auto_preview = service.preview(epub_path)
    single_preview = service.preview(epub_path, split_mode="single")
    result = service.import_translated_ebook(epub_path, duplicate_strategy="error", split_mode="single")

    assert auto_preview["split_method"] == "heading"
    assert auto_preview["toc_chapter_count"] == 0
    assert auto_preview["chapter_count"] == 2
    assert single_preview["split_method"] == "single"
    assert single_preview["chapter_count"] == 1
    assert single_preview["chapters"][0]["title"] == "Toàn bộ ebook"
    assert result["imported_chapters"] == 1
    book = get_book_by_title(temp_db_path, "Toàn Bản Dịch")
    assert book is not None
    chapters = list_chapters(temp_db_path, book["id"])
    assert chapters[0]["chapter_number"] == 1
    assert chapters[0]["title"] == "Toàn bộ ebook"
    imported_text = Path(chapters[0]["translated_text_path"]).read_text(encoding="utf-8")
    assert "Chương 1: Khai cục" in imported_text
    assert "Chương 2: Linh thạch" in imported_text


def test_kindle_formats_convert_to_epub_before_parsing(
    tmp_path: Path,
    temp_db_path: Path,
    monkeypatch,
) -> None:
    mobi_path = tmp_path / "translated.mobi"
    mobi_path.write_bytes(b"fake-mobi")
    service = EbookImportService(db_path=temp_db_path, data_dir=tmp_path / "data")
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        write_epub2_ncx_no_heading_epub(Path(command[2]))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(ebook_import_service.shutil, "which", lambda name: "/usr/bin/ebook-convert")
    monkeypatch.setattr(ebook_import_service.subprocess, "run", fake_run)

    preview = service.preview(mobi_path)

    assert preview["source_format"] == "mobi"
    assert preview["title"] == "Toc NCX Book"
    assert preview["split_method"] == "toc"
    assert preview["toc_chapter_count"] == 2
    assert commands[0][:2] == ["/usr/bin/ebook-convert", str(mobi_path)]
