import json
import os
from dataclasses import asdict, dataclass, field, fields

from .paths import data_dir


@dataclass
class Settings:
    last_dir: str = ""
    export_dir: str = ""
    export_format: str = "JPEG"
    export_width: int = 3000
    export_background: str = "white"     # white | transparent | studio | color
    export_color: str = "#ffffff"
    export_quality: int = 95
    board_color: str = "#ece6da"
    shadow: bool = True
    hide_lines: bool = True
    line_rules: list = field(default_factory=list)   # remembered cut/crease rules (roles.py)
    lens: float = 85.0
    straight: bool = True
    light: str = "original"              # preset name or "manual"
    light_x: float = -0.25
    light_y: float = 0.35
    light_strength: int = 12               # %
    light_exposure: int = 100              # %
    export_aspect: str = "4:5"
    export_fill: bool = True
    geometry: str = ""

    @classmethod
    def load(cls):
        p = os.path.join(data_dir(), "settings.json")
        try:
            with open(p, encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self):
        p = os.path.join(data_dir(), "settings.json")
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
