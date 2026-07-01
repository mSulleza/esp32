# Schematic — Integrated ESP32 AC Controller

Bare **ESP32-WROOM-32E** design with USB-C power+data, **CH340C** USB-UART with
auto-program (no manual BOOT/EN dance), **AMS1117-3.3** LDO, on-board **BME280**,
on-board IR receiver, and an IR-LED driver to an external-emitter header.

All KiCad symbol/footprint IDs are from the **standard KiCad 8 libraries** (no
custom symbols needed). Reference designators are used throughout.

---

## Block diagram

```
        ┌──────────┐   5V   ┌───────────┐  3V3   ┌──────────────────────┐
 USB-C ─┤ ESD prot ├───┬────┤ AMS1117-3 ├───┬────┤   ESP32-WROOM-32E     │
 (J1)   │ (U1)     │   │    │ LDO (U2)  │   │    │   (U4)               │
        └────┬─────┘   │    └───────────┘   │    │                      │
          D+ │ D-      │                    ├────┤ 3V3                  │
        ┌────┴─────┐   │                    │    │                      │
        │ CH340C   ├───┘ (VCC=3V3)          │  ┌─┤ IO21/IO22 (I2C)──┐   │
        │ USB-UART │  TXD/RXD  ┌─────────┐  │  │ │ IO14 (IR RX)     │   │
        │ (U3)     ├───────────┤ ESP UART│  │  │ │ IO4  (IR TX)     │   │
        │  DTR RTS ├──auto-rst─┤ EN/IO0  │  │  │ │ IO2  (LED)       │   │
        └──────────┘  (Q1,Q2)  └─────────┘  │  │ └──────────────────┘   │
                                            │  └────────────────────────┘
   3V3 ──┬─[4k7]─SDA  ┌─────────┐           │     IR RX │   IR TX │  LED │
         ├─[4k7]─SCL  │ BME280  │           │   ┌───────┴──┐  ┌───┴───┐ ┌┴──┐
         └────────────┤ (U5)    │           │   │ IR recv  │  │ Q3 NPN│ │D2 │
                      └─────────┘           │   │ (U6)+RC  │  │ driver│ │LED│
                                            └───┤ VCC      │  └───┬───┘ └───┘
                                                └──────────┘   J2 header
                                                              (ext IR LED)
```

---

## Net list (authoritative — wire to *this*)

Power & ground:

| Net | Members |
|-----|---------|
| `+5V` (VBUS) | J1.VBUS, U1.VBUS, U2.Vin, U3.VCC, C1(10µF), R_led(47Ω→J2), R_pwr(1k→D1) |
| `VREG3` | U3.V3 + C5(0.1µF→GND). CH340C runs off 5V; its internal-reg output V3 sets the UART logic level to a **safe 3.3 V** and is decoupled here — not tied to +3V3, which avoids two regulators fighting. |
| `+3V3` | U2.Vout, U4.VDD, U5.VDD, U5.VDDIO, U5.CSB, C3(10µF), C4(0.1µF), C6(0.1µF U5), C7(10µF U4), C8(0.1µF U4), R_EN(10k), R_IO0(10k), R_SDA(4k7), R_SCL(4k7), R_IRrx(100Ω) |
| `GND` | all GND pins, J1.GND+SHIELD, U1.GND, U2.GND, U3.GND, U4.GND(+thermal pad), U5.GND, U5.SDO, Q1.E?/…, C* grounds, buttons, LED cathodes returns |

USB:

| Net | Members |
|-----|---------|
| `USB_DP` | J1.A6, J1.B6, U1.IO(D+ side), U3.D+ |
| `USB_DM` | J1.A7, J1.B7, U1.IO(D- side), U3.D- |
| `CC1` | J1.A5 → R_CC1(5.1k) → GND |
| `CC2` | J1.B5 → R_CC2(5.1k) → GND |

UART + auto-program:

| Net | Members |
|-----|---------|
| `UART_TX` | U4.TXD0 (GPIO1) → U3.RXD |
| `UART_RX` | U4.RXD0 (GPIO3) → U3.TXD |
| `DTR` | U3.DTR# → Q1.E, Q2.B |
| `RTS` | U3.RTS# → Q2.E, Q1.B |
| `EN`  | U4.EN, R_EN(10k→3V3), C_EN(1µF→GND), SW1(EN btn→GND), Q2.C |
| `IO0` | U4.GPIO0, R_IO0(10k→3V3), SW2(BOOT btn→GND), Q1.C |

> **Auto-reset cross-couple (Q1, Q2 = NPN, e.g. MMBT3904):**
> Q1: base=`RTS`, emitter=`DTR`, collector=`IO0`.
> Q2: base=`DTR`, emitter=`RTS`, collector=`EN`.
> When DTR==RTS, neither conducts (no spurious reset); esptool's DTR/RTS toggling
> drives BOOT+RESET automatically. This is the standard NodeMCU/Espressif circuit.

Sensor (I²C):

| Net | Members |
|-----|---------|
| `I2C_SDA` (GPIO21) | U4.IO21, U5.SDA(=SDI), R_SDA(4k7→3V3) |
| `I2C_SCL` (GPIO22) | U4.IO22, U5.SCL(=SCK), R_SCL(4k7→3V3) |
| `+3V3`/`GND` set BME280 mode: U5.CSB→`+3V3` (I²C), U5.SDO→`GND` (addr **0x76**) |

IR receive (learn):

| Net | Members |
|-----|---------|
| `IRRX_VCC` | `+3V3` → R_IRrx(100Ω) → U6.VCC, C_IRrx(4.7µF)→GND |
| `IR_RX` (GPIO14) | U4.IO14 ← U6.OUT |
| `GND` | U6.GND |

IR transmit (drive external LED):

| Net | Members |
|-----|---------|
| `IR_TX_GATE` (GPIO4) | U4.IO4 → R_base(1k) → Q3.base |
| `IR_LED_A` | `+5V` → R_led(47Ω) → D3.A (on-board SMD IR LED anode) |
| `IR_LED_K` | D3.K (cathode) → Q3.collector |
| `GND` | Q3.emitter |

Status / power indication:

| Net | Members |
|-----|---------|
| `STATUS_LED` (GPIO2) | U4.IO2 → R_led2(330Ω) → D2.anode; D2.cathode→GND |
| `+5V` → R_pwr(1k) → D1.anode; D1.cathode→GND (optional power LED) |

> **Strapping pin caution:** GPIO2 drives the status LED **active-high to GND** so
> it can't be pulled high at boot (which would block download mode). Leave
> **GPIO12 and GPIO15 unused** (don't add pull-ups). GPIO0 has its 10k pull-up +
> BOOT button only.

---

## Sub-circuit detail

### 1. USB-C input + ESD (J1, U1)
```
USB-C (J1, 16-pin)         USBLC6-2SC6 (U1, SOT-23-6)
  VBUS(A4,A9,B4,B9) ─┬────────── VBUS pin ───► +5V
  GND (A1,A12,B1,B12)┴─ GND ; SHIELD ─[optional ferrite/cap]─ GND
  D+ (A6,B6) ─────────────► U1 I/O ──► USB_DP ──► U3.D+
  D- (A7,B7) ─────────────► U1 I/O ──► USB_DM ──► U3.D-
  CC1(A5) ─[5.1k]─ GND      CC2(B5) ─[5.1k]─ GND   (advertise sink, draw 5V)
```
Tie the two D+ pads together and the two D- pads together. CC pulldowns are
**5.1 kΩ each** (not shared). Add `C1 = 10 µF` bulk on +5V at the connector.

### 2. 3.3 V regulator (U2)
```
+5V ─┬─[C1 10µF]─ GND
     └── Vin  AMS1117-3.3  Vout ──┬── +3V3
              GND ── GND          ├─[C3 10µF]─ GND
                                  └─[C4 0.1µF]─ GND
```
AMS1117 dropout ~1.1 V → fine from 5 V. (Low-Iq alt: ME6211C33; AMS1117 is a
JLC **Basic** part, so it's the cheap default.)

### 3. CH340C USB-UART + auto-program (U3, Q1, Q2)
```
+5V ─── U3.VCC
U3.V3 ──┬── VREG3   (internal 3.3V reg out; sets UART logic level)
        └─[C5 0.1µF]─ GND
U3.TXD ──► UART_RX (ESP RXD0/GPIO3)
U3.RXD ◄── UART_TX (ESP TXD0/GPIO1)
U3.UD+ ──► USB_DP        U3.UD- ──► USB_DM
U3.DTR# ─┬─ Q1.E ─┬─ Q2.B
U3.RTS# ─┼─ Q2.E ─┼─ Q1.B
         └─ Q1.C → IO0     └─ Q2.C → EN     (cross-coupled, see note above)
```
CH340C is powered from **5 V**, but its `V3` pin is the internal 3.3 V regulator
output that sets the **TXD/RXD logic level**, so the UART lines swing 0–3.3 V —
safe for the ESP32. `V3` gets its own decoupling cap (it is *not* tied to the
main +3V3 rail, which would put two regulator outputs on one net).

### 4. ESP32-WROOM-32E (U4)
```
+3V3 ─┬─ U4.3V3   EN ── R_EN 10k → +3V3 ; C_EN 1µF → GND ; SW1 → GND
      ├─[C_b 10µF]─ GND
      └─[C_b2 0.1µF]─ GND
GND  ── U4.GND (×N) + thermal/exposed pad (stitch vias)
IO0  ── R_IO0 10k → +3V3 ; SW2 → GND
Used GPIOs: IO21=SDA, IO22=SCL, IO14=IR_RX, IO4=IR_TX_GATE, IO2=STATUS_LED,
            TXD0/IO1=UART_TX, RXD0/IO3=UART_RX
Leave unused & DO NOT strap: IO12, IO15.
```
Keep the WROOM antenna end at the **board edge with a copper keepout** (see
`LAYOUT.md`).

### 5. BME280 (U5)
```
+3V3 ─┬─ U5.VDD ─┬─ U5.VDDIO ─┬─ U5.CSB(→I²C mode)
      └─[C6 0.1µF]─ GND
U5.SDA ── I2C_SDA ─[R_SDA 4k7]─ +3V3
U5.SCL ── I2C_SCL ─[R_SCL 4k7]─ +3V3
U5.SDO ── GND   (I²C address 0x76)   U5.GND ── GND
```

### 6. IR receiver (U6) — learn mode
```
+3V3 ─[R_IRrx 100Ω]─┬─ U6.VCC
                    └─[C_IRrx 4.7µF]─ GND
U6.OUT ── IR_RX (GPIO14)         U6.GND ── GND
```
The 100 Ω + 4.7 µF supply filter is the datasheet-recommended noise filter.

### 7. IR transmit driver (Q3, D3)
```
GPIO4 ─[R_base 1k]─ Q3.base
+5V ─[R_led 47Ω]─ D3.A ──(on-board SMD IR LED, 940nm 1206)
                  D3.K ── Q3.collector
Q3.emitter ── GND
```
On-board SMD 940 nm IR emitter (D3) — fully machine-assembled. It's a top-view
LED, so **the board faces the AC** to transmit. For more range, parallel a second
1206 IR LED (each with its own 47 Ω).

---

## Reference designator summary

| Ref | Part | Net role |
|-----|------|----------|
| J1 | USB-C receptacle (16P) | power + data in |
| D3 | SMD IR LED 1206 | on-board IR emitter |
| U1 | USBLC6-2SC6 | USB ESD protection |
| U2 | AMS1117-3.3 | 3.3 V LDO |
| U3 | CH340C | USB-UART |
| U4 | ESP32-WROOM-32E | MCU + Wi-Fi |
| U5 | BME280 | temp/humidity |
| U6 | IR receiver 38 kHz | IR learn |
| Q1,Q2 | NPN (MMBT3904) | auto-program |
| Q3 | NPN (MMBT2222A) | IR LED driver |
| D1,D2 | LED 0603 | power / status |
| SW1,SW2 | tact switch | EN / BOOT |
| R_*, C_* | passives | see netlist |

Continue to [`BOM.csv`](BOM.csv) for exact parts and [`LAYOUT.md`](LAYOUT.md) for
the board.
