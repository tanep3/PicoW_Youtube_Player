# Third-party notices

`pico/third_party/tjpgd/lgfx_tjpgd.c` and `pico/third_party/tjpgd/lgfx_tjpgd.h` were copied unchanged from the local LovyanGFX source at `/home/tane/pico/LovyanGFX/src/lgfx/utility/` for this diagnostic firmware. Only these two decoder files are included; the LovyanGFX display framework is not linked.

TJpgDec is Copyright (C) 2019 ChaN. The source header states: “No restriction on use. You can use, modify and redistribute it for personal, non-profit or commercial products UNDER YOUR RESPONSIBILITY. Redistributions of source code must retain the above copyright notice.” The source notes modifications for LGFX by lovyan03 in 2020. The original source and its full copyright/license text remain in the copied C and H file headers.


`pico/lcd_gamma_lgfx.h` contains only the E0/E1 ST7735S gamma data pair from the local LovyanGFX `src/lgfx/v1/panel/Panel_ST7735.hpp`, `Panel_ST7735S::Rcmd2`. The panel framework is not linked. The upstream panel file identifies lovyan03 as author and the FreeBSD license. The original local license bundle, including the LovyanGFX copyright and redistribution conditions, is preserved in `pico/third_party/lovyangfx/LICENSE.txt`. The exact source file SHA256 and gamma bytes are recorded in `docs/diagnostics/LCD_GAMMA_AB.md`.


## Project license and excluded third-party content

The root [MIT LICENSE](LICENSE), Copyright (c) 2026 Tane Channel Technology,
applies to this project's original work. It does not replace third-party
licenses or the copyright notices retained in their source files.

The isolated diagnostic driver in `diagnostics/pico/cyw43-driver/` retains
[LICENSE](diagnostics/pico/cyw43-driver/LICENSE) and
[LICENSE.RP](diagnostics/pico/cyw43-driver/LICENSE.RP), Copyright (C) 2019-2022
George Robotics Pty Ltd. The Raspberry Pi-specific terms are provided for
use with RP2040 or other Raspberry Pi semiconductor devices. These driver
files and the existing license texts are unchanged by the documentation and
case import. The normal build uses the separately installed Pico SDK; its
components retain their own licenses.

YouTube videos, thumbnails and the comparison photographs retain the rights
of their respective owners; the project MIT license does not grant rights
to those media. The case v3 files were imported from the user-selected
Library packages without modifying their contents. Their source identities
and hashes are recorded in
[SOURCE_MANIFEST.json](hardware/case/slim-v3/SOURCE_MANIFEST.json).
