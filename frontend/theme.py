"""Tema visual oscuro del dashboard, construido sobre el tema ttk 'clam'."""

from tkinter import font as tkfont, ttk

COLORES = {
    "fondo": "#0b1120",
    "superficie": "#111827",
    "tarjeta": "#1e293b",
    "fila_alterna": "#223047",
    "borde": "#334155",
    "texto": "#e2e8f0",
    "tenue": "#94a3b8",
    "acento": "#22d3ee",
    "acento_activo": "#67e8f9",
    "texto_acento": "#0b1120",
    "exito": "#4ade80",
    "fondo_exito": "#14352a",
    "alerta": "#fbbf24",
    "fondo_alerta": "#3b2a0c",
    "peligro": "#f87171",
    "fondo_peligro": "#3f1d24",
}


def _familia(raiz, candidatas):
    disponibles = {familia.lower() for familia in tkfont.families(raiz)}
    return next((f for f in candidatas if f.lower() in disponibles), "TkDefaultFont")


def aclarar(color, proporcion=0.4):
    """Mezcla un color #rrggbb con blanco para que se lea sobre fondo oscuro."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (round(c + (255 - c) * proporcion) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def aplicar_tema(raiz):
    """Configura estilos ttk y colores por defecto; devuelve (colores, fuentes)."""
    c = COLORES
    familia = _familia(raiz, ("Segoe UI", "Inter", "Helvetica Neue", "DejaVu Sans", "Helvetica"))
    mono = _familia(raiz, ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New"))
    f = {
        "base": (familia, 10),
        "pequena": (familia, 9),
        "negrita": (familia, 10, "bold"),
        "seccion": (familia, 11, "bold"),
        "titulo": (familia, 15, "bold"),
        "reloj": (familia, 22, "bold"),
        "kpi": (familia, 18, "bold"),
        "marcador": (familia, 9, "bold"),
        "parada": (familia, 11, "bold"),
        "mono": (mono, 10),
    }

    raiz.configure(background=c["fondo"])
    raiz.option_add("*TCombobox*Listbox.background", c["tarjeta"])
    raiz.option_add("*TCombobox*Listbox.foreground", c["texto"])
    raiz.option_add("*TCombobox*Listbox.selectBackground", c["acento"])
    raiz.option_add("*TCombobox*Listbox.selectForeground", c["texto_acento"])
    raiz.option_add("*TCombobox*Listbox.font", f["base"])
    raiz.option_add("*Menu.background", c["tarjeta"])
    raiz.option_add("*Menu.foreground", c["texto"])
    raiz.option_add("*Menu.activeBackground", c["acento"])
    raiz.option_add("*Menu.activeForeground", c["texto_acento"])
    raiz.option_add("*Menu.selectColor", c["acento"])
    raiz.option_add("*Menu.font", f["base"])

    estilo = ttk.Style(raiz)
    estilo.theme_use("clam")
    estilo.configure(
        ".", background=c["fondo"], foreground=c["texto"], font=f["base"],
        fieldbackground=c["tarjeta"], bordercolor=c["borde"],
        lightcolor=c["tarjeta"], darkcolor=c["tarjeta"], troughcolor=c["superficie"],
        focuscolor=c["acento"], selectbackground=c["acento"],
        selectforeground=c["texto_acento"], insertcolor=c["texto"],
    )

    # Marcos y etiquetas por superficie
    for nombre, fondo in (("", "fondo"), ("Card", "tarjeta"), ("Header", "superficie")):
        prefijo = f"{nombre}." if nombre else ""
        estilo.configure(f"{prefijo}TFrame", background=c[fondo])
        estilo.configure(f"{prefijo}TLabel", background=c[fondo], foreground=c["texto"])
        estilo.configure(
            f"{nombre}Muted.TLabel", background=c[fondo], foreground=c["tenue"],
            font=f["pequena"],
        )
    estilo.configure("Title.TLabel", background=c["superficie"], font=f["titulo"])
    estilo.configure("Clock.TLabel", background=c["superficie"], foreground=c["acento"],
                     font=f["reloj"])
    estilo.configure("Section.TLabel", background=c["tarjeta"], font=f["seccion"])
    estilo.configure("Field.TLabel", background=c["tarjeta"], foreground=c["tenue"],
                     font=f["negrita"])
    estilo.configure("KpiValue.TLabel", background=c["tarjeta"], foreground=c["texto"],
                     font=f["kpi"])
    estilo.configure("KpiCaption.TLabel", background=c["tarjeta"], foreground=c["tenue"],
                     font=f["pequena"])
    estilo.configure("PillOk.TLabel", background=c["fondo_exito"], foreground=c["exito"],
                     font=f["negrita"], padding=(10, 4))
    estilo.configure("PillWarn.TLabel", background=c["fondo_alerta"], foreground=c["alerta"],
                     font=f["negrita"], padding=(10, 4))

    # Botones
    estilo.configure(
        "TButton", background=c["superficie"], foreground=c["texto"], bordercolor=c["borde"],
        lightcolor=c["superficie"], darkcolor=c["superficie"], padding=(12, 6), relief="flat",
    )
    estilo.map(
        "TButton",
        background=[("disabled", c["superficie"]), ("pressed", c["borde"]),
                    ("active", c["borde"])],
        foreground=[("disabled", c["borde"])],
    )
    estilo.configure(
        "Accent.TButton", background=c["acento"], foreground=c["texto_acento"],
        bordercolor=c["acento"], lightcolor=c["acento"], darkcolor=c["acento"],
        font=f["negrita"],
    )
    estilo.map("Accent.TButton",
               background=[("pressed", c["acento_activo"]), ("active", c["acento_activo"])])
    estilo.configure(
        "Header.TButton", background=c["tarjeta"], lightcolor=c["tarjeta"],
        darkcolor=c["tarjeta"], bordercolor=c["borde"],
    )
    estilo.map("Header.TButton",
               background=[("pressed", c["borde"]), ("active", c["borde"])])
    estilo.configure(
        "Danger.TButton", background=c["tarjeta"], foreground=c["peligro"],
        bordercolor=c["tarjeta"], padding=(8, 2), font=f["pequena"],
    )
    estilo.map(
        "Danger.TButton",
        background=[("disabled", c["tarjeta"]), ("active", c["fondo_peligro"])],
        foreground=[("disabled", c["borde"])],
    )
    estilo.configure(
        "TMenubutton", background=c["superficie"], foreground=c["texto"],
        bordercolor=c["borde"], arrowcolor=c["tenue"], padding=(10, 5), relief="flat",
    )
    estilo.map("TMenubutton", background=[("active", c["borde"])])

    # Campos
    estilo.configure(
        "TCombobox", fieldbackground=c["superficie"], background=c["superficie"],
        foreground=c["texto"], arrowcolor=c["tenue"], bordercolor=c["borde"],
        lightcolor=c["superficie"], darkcolor=c["superficie"], padding=(6, 4),
    )
    estilo.map(
        "TCombobox",
        fieldbackground=[("readonly", c["superficie"])],
        foreground=[("readonly", c["texto"])],
        selectbackground=[("readonly", c["superficie"])],
        selectforeground=[("readonly", c["texto"])],
        bordercolor=[("focus", c["acento"]), ("hover", c["acento"])],
        arrowcolor=[("hover", c["acento"])],
    )
    estilo.configure(
        "Card.TCheckbutton", background=c["tarjeta"], foreground=c["texto"],
        indicatorbackground=c["superficie"], indicatorforeground=c["acento"],
    )
    estilo.map("Card.TCheckbutton", background=[("active", c["tarjeta"])])

    # Tablas sin borde, con encabezado plano
    estilo.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    estilo.configure(
        "Treeview", background=c["tarjeta"], fieldbackground=c["tarjeta"],
        foreground=c["texto"], rowheight=26, borderwidth=0,
    )
    estilo.map("Treeview", background=[("selected", c["borde"])],
               foreground=[("selected", c["texto"])])
    estilo.configure(
        "Treeview.Heading", background=c["superficie"], foreground=c["tenue"],
        font=f["pequena"], relief="flat", padding=(6, 5), bordercolor=c["superficie"],
        lightcolor=c["superficie"], darkcolor=c["superficie"],
    )
    estilo.map("Treeview.Heading", background=[("active", c["borde"])])

    estilo.configure(
        "Vertical.TScrollbar", background=c["borde"], troughcolor=c["tarjeta"],
        bordercolor=c["tarjeta"], lightcolor=c["borde"], darkcolor=c["borde"],
        arrowcolor=c["tenue"], gripcount=0, arrowsize=12,
    )
    estilo.map("Vertical.TScrollbar", background=[("active", c["tenue"])])

    # Pestañas
    estilo.configure("TNotebook", background=c["fondo"], borderwidth=0,
                     tabmargins=(0, 0, 0, 0))
    estilo.configure(
        "TNotebook.Tab", background=c["superficie"], foreground=c["tenue"],
        padding=(14, 6), borderwidth=0, font=f["negrita"],
        lightcolor=c["superficie"], bordercolor=c["fondo"],
    )
    estilo.map(
        "TNotebook.Tab",
        background=[("selected", c["tarjeta"]), ("active", c["borde"])],
        foreground=[("selected", c["acento"]), ("active", c["texto"])],
        lightcolor=[("selected", c["tarjeta"])],
    )
    return c, f
