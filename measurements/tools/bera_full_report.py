"""Assemble the full 2026-10-16 BERA evening report as one PDF.

Usage: bera_full_report.py <out.pdf>

Text pages are written here; every figure comes from the analysis scripts
(bera_analysis.py, analysis_eeg_eog_emg.py, analysis_heart_resp.py,
analysis_tech_artefacts.py, analysis_mic_audio.py) and is placed one per page.
"""
import os
import sys
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.backends.backend_pdf import PdfPages

HERE = os.path.dirname(os.path.abspath(__file__))
B = os.path.join(HERE, "..", "2026-10-16_bera")
A = os.path.join(B, "analysis")
E = os.path.join(HERE, "..", "2026-10-16_ecg_drl")
INK, MUTED, ACC = "#1a1a1a", "#666666", "#2a78d6"
A4P, A4L = (8.27, 11.69), (11.69, 8.27)
page_no = [0]


def footer(fig):
    page_no[0] += 1
    fig.text(0.5, 0.015, f"Wireless BERA · Messabend 16./17.10.2026 · Seite {page_no[0]}",
             ha="center", fontsize=7, color=MUTED)


def text_page(pdf, title, blocks, size=A4P):
    """blocks: list of (kind, text); kind in h, p, b (bullet), t (table rows as list)."""
    fig = plt.figure(figsize=size)
    W = 95 if size == A4P else 140
    y = 0.95
    fig.text(0.07, y, title, fontsize=16, weight="bold", color=INK, va="top")
    y -= 0.05
    for kind, txt in blocks:
        if kind == "h":
            y -= 0.012
            fig.text(0.07, y, txt, fontsize=11.5, weight="bold", color=ACC, va="top")
            y -= 0.03
        elif kind in ("p", "b"):
            lines = textwrap.wrap(txt, W - (4 if kind == "b" else 0))
            for i, ln in enumerate(lines):
                x = 0.07
                if kind == "b":
                    if i == 0:
                        fig.text(x, y, "•", fontsize=9, color=INK, va="top")
                    x = 0.09
                fig.text(x, y, ln, fontsize=9, color=INK, va="top")
                y -= 0.0185
            y -= 0.006
        elif kind == "t":
            rows = txt
            ncol = len(rows[0])
            cw = [0.20] + [(0.86 - 0.20) / (ncol - 1)] * (ncol - 1)
            for r, row in enumerate(rows):
                x = 0.07
                for c, cell in enumerate(row):
                    fig.text(x, y, cell, fontsize=8.3, va="top", color=INK,
                             weight="bold" if r == 0 or c == 0 else "normal", wrap=True)
                    x += cw[c]
                y -= 0.032 if r else 0.026
                if r == 0:
                    fig.add_artist(plt.Line2D([0.07, 0.93], [y + 0.008, y + 0.008], color=MUTED, lw=0.6))
            y -= 0.01
    footer(fig)
    pdf.savefig(fig)
    plt.close(fig)


def fig_page(pdf, path, section, caption):
    img = mpimg.imread(path)
    h, w = img.shape[:2]
    size = A4L if w / h > 1.05 else A4P
    fig = plt.figure(figsize=size)
    fig.text(0.05, 0.965, section, fontsize=9, color=ACC, weight="bold", va="top")
    for i, ln in enumerate(textwrap.wrap(caption, 150 if size == A4L else 105)):
        fig.text(0.05, 0.94 - i * 0.022, ln, fontsize=9, color=INK, va="top")
    top = 0.94 - 0.022 * len(textwrap.wrap(caption, 150 if size == A4L else 105)) - 0.01
    ax = fig.add_axes([0.03, 0.035, 0.94, top - 0.035])
    ax.imshow(img)
    ax.set_axis_off()
    ax.set_anchor("N")
    footer(fig)
    pdf.savefig(fig, dpi=120)
    plt.close(fig)


FIGS = [
    ("1 · BERA", os.path.join(B, "electrode_placement_mastoid.jpg"),
     "Elektrode− am linken Mastoid. Gelbe Leitung um den Druckknopf gewickelt, daneben ein loses Drahtende; das "
     "schwarze Ohrhörerkabel läuft direkt über die Elektrode – Hauptweg des elektrischen Klick-Artefakts."),
    ("1 · BERA", os.path.join(B, "bera_analysis.png"),
     "Läufe 1 und 2: Mittel, Polaritäten getrennt, Filtervarianten, Permutationstest. Lauf 2 (liegend, Klick 0,05): "
     "Welle-V-Kandidat bei 6,1 ms (95 % KI 5,8–6,3 ms), 164 nV, p = 0,001."),
    ("1 · BERA", os.path.join(B, "4_control_vs_run2.png"),
     "Kontrolle: Lauf 4 mit Ohrhörer außerhalb des Ohrs zeigt bei 6 ms nichts (p = 0,44). Er ist allerdings "
     "rauschiger (3,5–5,5 µV pro Sweep), die Kontrolle stützt den Befund, beweist ihn nicht."),
    ("1 · BERA", os.path.join(B, "3_blocks_analysis.png"),
     "Lauf 3 in Blöcken (Klick 0,035 / stumme Kontrolle / Tonpuls 2 kHz): keine signifikante Antwort, weil "
     "die Muskelspannung hoch blieb (Sweep-SD 4,7–7 µV)."),
]
SECTIONS = [
    ("2 · EEG, Augen, Muskeln", "eeg_", {
        "eeg_01": "Alle Läufe 0,1–30 Hz mit erkannten Lidschlägen und langsamen Augenbewegungen.",
        "eeg_02": "Spektren je Bedingung: Alpha-Peak bei 9,75–10 Hz im Liegen (+10–12 dB), sitzend schwächer.",
        "eeg_03": "Relative und absolute Bandleistungen. Delta ist überwiegend EOG (Stirnelektrode).",
        "eeg_04": "Lauf 2: Spektrogramm, Bänder, Alpha-Index, EMG und Augenereignisse über die Zeit.",
        "eeg_05": "Lauf 3 mit den Blöcken A/B/C.",
        "eeg_06": "Lauf 4.",
        "eeg_07": "Kontrollen: Alpha ist kein WLAN-Beacon-Artefakt (zufällige Phase bei 9,766 Hz, fehlt im "
                  "Mikrofon und im Brust-EKG).",
        "eeg_08": "Beispiele: Lidschlag (~100 µV), langsame Augenbewegung, Unruhephase, Lagewechsel.",
        "eeg_09": "Lidschläge pro Minute: sitzend 7/min, Unruhe 26/min, ruhig liegend 0,5–2/min.",
        "eeg_10": "EMG (30–300 / 300–2000 Hz) gegen das BERA-Sweep-Rauschen über die Zeit.",
        "eeg_11": "Was treibt das BERA-Rauschen? EMG erklärt R² = 0,94, EOG nur 0,11, EEG 0,25.",
        "eeg_12": "Die ersten 160 s von Lauf 2: Sweep-SD fällt von 12 auf 2 µV, als sich die Muskeln lösen.",
        "eeg_13": "Kurze EMG-Bursts in Ruhe, am ehesten Schlucken.",
        "eeg_14": "Sigma-Hüllkurve 11–15 Hz: keine Schlafspindeln, kein Schlaf.",
        "eeg_15": "Nutzbarkeit je 4-s-Fenster (sauber / Augen / Muskel / grobes Artefakt).",
        "eeg_16": "EMG-Spektren: Muskelbuckel bei 100–300 Hz, über 1,5 kHz gleicher Gerätegrund (~32 nV/√Hz).",
    }),
    ("3 · Herz und Atmung", "heart_", {
        "heart_01": "Brust-EKG: gemittelter Schlag der fünf Läufe und Herzfrequenz über die Zeit.",
        "heart_02": "HRV: Poincaré, SDNN 32–64 ms, RMSSD 22–42 ms; LF/HF nur orientierend (< 2 min). "
                    "Das 20-ms-Raster der RR-Intervalle in Brust 1 und 5 fällt mit den Läufen mit starkem "
                    "Netzbrumm zusammen (20 ms = 1/50 Hz) und ist vermutlich Brumm, nicht der Datenpfad.",
        "heart_03": "Atmung am Brust-EKG: EDR (QRS-Amplitude) robust, 14–16/min; RSA und Basislinie im Vergleich.",
        "heart_04": "Am Kopf ist kein EKG nachweisbar: Injektionstest zeigt, das Kopf-QRS ist ≲ 10–15 µV.",
        "heart_05": "Keine Herzfrequenz-Linie im Sweep-Rauschen.",
        "heart_06": "Atmung am Kopf nicht messbar – Lidschläge dominieren die Basislinie.",
        "heart_07": "Simulierter Herzrest im ABR-Mittel: < 1 nV, vernachlässigbar.",
        "heart_08": "Herzfrequenz und Atemfrequenz über den Abend (Kopfläufe: nicht messbar).",
    }),
    ("4 · Technik: WLAN, Netz, Akku, Quantisierung", "tech_", {
        "tech_01": "Rauschdichte CH2/CH1 aller Läufe gegen die theoretischen Rauschböden.",
        "tech_02": "Keine WLAN-Linien bei 187,5·k Hz; 1-kHz-Kamm nur sitzend; Linie bei 6282 Hz ungeklärt.",
        "tech_03": "Mittelung über Paketperiode und Beacon: keine WLAN-Kopplung im µV-Signal.",
        "tech_04": "Spektrogramme und Burst-Suche: keine Breitband-Bursts.",
        "tech_05": "Paket- und Klickraster laufen gegeneinander – ein Paket-Artefakt mittelt sich weg.",
        "tech_06": "Paketverlust ~1,1 % über die Zeit, unabhängig von Ansagen.",
        "tech_07": "Alle Lücken auf einem 524-ms-Raster (512 TU) – periodischer WLAN-Vorgang (Router/Laptop).",
        "tech_08": "Netzbrumm am Kopf 0,2–6 µV statt 1500 µV an der Brust ohne DRL; f0 49,98–50,01 Hz.",
        "tech_09": "Nach dem Kammfilter keine Netzlinie mehr nachweisbar.",
        "tech_10": "Akku 3,42 → 3,23 V: kein Anstieg von Rauschen, Brumm oder Spurs.",
        "tech_11": "Karte aller Schmalbandlinien je Lauf.",
        "tech_12": "Quantisierung: CH2 nutzt nur 1,7 % des int16-Bereichs, ~20 % der HF-Rauschleistung ist "
                   "Quantisierung; Dithering reicht für die Mittelung.",
        "tech_13": "DC-Offset < 2 µV; −0,5 LSB stammen vom Abschneiden (>> 8) in der Firmware.",
        "tech_14": "Reizartefakt: biphasisch (dI/dt) – Kopplung über das Ohrhörerkabel.",
        "tech_15": "Artefakt gegen Klickamplitude; das Mikrofon-Übersprechen ist exakt linear.",
        "tech_16": "Qualitätskarte je Sweep: Technik sauber, begrenzend ist die Biologie.",
    }),
    ("5 · Mikrofon und Geräusche", "mic_", {
        "mic_01_uebersicht_lauf0": "Lauf 0: nur Grundrauschen.",
        "mic_01_uebersicht_lauf1": "Lauf 1: Pegel, Spektrogramm, Ereignisse (Husten?, Rascheln).",
        "mic_01_uebersicht_lauf2": "Lauf 2 (Mikrofon in den ersten 20 s aus Datenschutzgründen stummgeschaltet).",
        "mic_01_uebersicht_lauf3": "Lauf 3: Klicks in A, Stille in B, 2-kHz-Linie in C, Ansagen.",
        "mic_01_uebersicht_lauf4": "Lauf 4: Ohrhörer draußen – akustischer Klick bei 2,5 kHz, Rascheln.",
        "mic_02": "Ansagen „Teil zwei/drei“: nur ~3 dB über dem Rauschen, nicht verständlich.",
        "mic_03": "Ereigniskatalog: Husten, Knacken, Schlucken, Rascheln, Atem.",
        "mic_04": "Klick-gemittelte Mikrofonspur: elektrisches Übersprechen bei jedem Klick.",
        "mic_05": "Akustischer Klick nur mit Ohrhörer draußen (+20–30 dB) – Sitzkontrolle möglich.",
        "mic_06": "Klickmonitor über die Zeit: zeigt, wann der Ohrhörer verrutscht.",
        "mic_07": "Mikrofon-Rauschen sitzt auf dem int16-Quantisierungsboden.",
        "mic_08": "Kohärenz Mikrofon ↔ Biosignal ≈ 0: kein Übersprechen außer dem Reiz.",
        "mic_09": "Atem-Modulation im Mikrofon nur schwach (Lauf 4).",
        "mic_10": "Das Biosignal hörbar gemacht (Spektrogramm der Audio-Ausschnitte).",
    }),
]

SUMMARY = [
    ("h", "Was wurde gemessen"),
    ("p", "Fünf Brust-EKG-Läufe (mit/ohne DRL, Apple-Watch-Vergleich) und fünf Kopf-Läufe für die Klick-BERA "
          "(Stirn+ / Mastoid links− / DRL Mastoid rechts, Klick 21,1/s alternierend, nur linkes Ohr), 22:38–00:12. "
          "Danach war der Akku leer (3,23 V)."),
    ("h", "Wichtigste Ergebnisse"),
    ("b", "BERA: In Lauf 2 (liegend, Klick 0,05) eine signifikante Antwort, Welle-V-Kandidat bei 6,1 ms, 164 nV, "
          "p = 0,001. Beide Polaritäten zeigen sie, die Kontrolle mit Ohrhörer außerhalb des Ohrs nicht."),
    ("b", "Das BERA-Rauschen wird fast vollständig von Muskelspannung bestimmt (R² = 0,94). Netzbrumm, WLAN, Herz "
          "und Akku spielen keine Rolle. Entspannt liegen bringt 2 µV pro Sweep, angespannt 5–7 µV."),
    ("b", "DRL wirkt: am Kopf nur 0,2–6 µV Netzbrumm, an der Brust ohne DRL 1500 µV."),
    ("b", "EEG: klarer Alpha-Rhythmus bei ~10 Hz im Liegen; Lidschläge gut erkennbar; kein Schlaf."),
    ("b", "Herz: an der Brust Puls, HRV und Atmung (14–16/min) gut; am Kopf kein EKG (< 10–15 µV)."),
    ("b", "Technik: Paketverlust 1,1 % auf einem festen 524-ms-Raster des WLANs; keine WLAN-Kopplung ins Signal; "
          "16-bit-Auflösung ist knapp (CH2 nutzt 1,7 % des Bereichs, Mikrofon am Quantisierungsboden)."),
    ("b", "Mikrofon: taugt als Klick-Monitor (t = 0, Polarität, Amplitude) und als Sitzkontrolle des Ohrhörers."),
    ("h", "Wo sind die Daten brauchbar?"),
    ("t", [["Signal", "Wo brauchbar", "Wofür", "Nicht brauchbar"],
           ["ABR / BERA", "Lauf 2 ab ~130 s", "Welle V, Latenz", "Lauf 3 A/C, Lauf 1 (zu rauschig)"],
           ["EEG Alpha", "Läufe 2 (ab 130 s), 3, 4", "Entspannung, Wachheit", "Lauf 0, Lauf 1 teilweise"],
           ["Augen (EOG)", "alle Kopfläufe", "Lidschläge, Wachheit", "absolute Blickposition"],
           ["Muskel (EMG)", "alle Kopfläufe", "Sweep-Gating, Lagerung", "—"],
           ["EKG / HRV", "Brustläufe 3, 4", "Puls, HRV, Atmung", "alle Kopfläufe"],
           ["Atmung", "Brust (EDR)", "Atemfrequenz", "Kopf"],
           ["Mikrofon", "alle Läufe", "Klick-Monitor, Artefakt-Flag", "Sprache, Umgebungslärm"]]),
]
IDEAS = [
    ("h", "Für die nächste BERA-Sitzung"),
    ("b", "Akku voll, frische Elektroden, Haut anrauen; Elektrodenleitungen mit Clip statt gewickelt; "
          "Ohrhörerkabel nach vorn, weg von den Elektroden."),
    ("b", "Liegend mit Nackenkissen, 2 min Ruhe vor dem Start; keine gesprochenen Ansagen während der Aufnahme."),
    ("b", "Pegelreihe 0,1 / 0,05 / 0,025 mit eingestreuter Kontrolle (Ohrhörer draußen) – Latenz-Intensitäts-Kurve."),
    ("b", "EMG-Gate live: 30–300-Hz-RMS mitlaufen lassen und Blöcke > 3,5 µV verwerfen oder abwerten."),
    ("h", "Firmware"),
    ("b", "24-bit-Übertragung oder digitale Verstärkung vor dem int16-Schnitt, Runden statt >> 8."),
    ("b", "Exakte Klick-Onset- und Polaritätsmarken im Paketkopf; Akku, Lückenzähler und RSSI in den Header."),
    ("b", "Mikrofon-PGA +30–40 dB; Codec-Hochpass per UI schaltbar (für EKG/EEG aus)."),
    ("b", "Größerer Sendepuffer / Nachsenden per Sequenznummer gegen die 10-ms-Ausfälle im 524-ms-Raster."),
    ("h", "Weitere Messideen"),
    ("b", "Berger-Test (Augen auf/zu) und Oz–Mastoid für echtes okzipitales Alpha."),
    ("b", "EKG als Zeitreferenz während der BERA (Brustelektroden statt Mikrofon auf CH1 oder Watch/PPG)."),
    ("b", "Impedanz-Pneumographie: kleiner DAC-Träger über die Elektroden, Atmung aus der Modulation."),
    ("b", "Kalibrierung des Klickpegels mit Schallpegelmesser, damit der Pegel in dB angegeben werden kann."),
    ("b", "Längerer Liegend-Versuch (20–30 min) mit Kinn-EMG: Einschlafen, Spindeln, Tonusabfall."),
    ("h", "Grenzen"),
    ("p", "Ein einzelner Proband und ein Abend; der Klickpegel ist nicht kalibriert; die Kontrolle war rauschiger "
          "als der Lauf mit Antwort. Kein medizinischer Befund."),
]

out = sys.argv[1]
with PdfPages(out) as pdf:
    text_page(pdf, "Wireless BERA – Messabend 16./17.10.2026", SUMMARY)
    for sec, path, cap in FIGS:
        fig_page(pdf, path, sec, cap)
    for sec, prefix, caps in SECTIONS:
        for f in sorted(os.listdir(A)):
            if f.startswith(prefix) and f.endswith(".png"):
                key = next((k for k in caps if f.startswith(k)), None)
                fig_page(pdf, os.path.join(A, f), sec, caps.get(key, f))
    text_page(pdf, "Ideen und nächste Schritte", IDEAS)
    d = pdf.infodict()
    d["Title"] = "Wireless BERA – Messabend 16./17.10.2026"
    d["Author"] = "Nathan Scheufele"
print(out, page_no[0], "Seiten")
