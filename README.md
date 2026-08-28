# ha-solarmodbus

**Local Modbus integration for Solarman‑compatible inverters (Deye, Sunsynk, LuxPower, Sofar…).  
100% local · Multi‑brand · Extensible · No cloud required**

---

## 📌 Important Notice

This integration uses the **public inverter register definitions** from the  
**Solarman Python project by Stephan Joubert**, specifically the directory: inverter_definitions/

These YAML files are used **as reference material** for Modbus register mapping.  
This project is **not** a fork of his work, and all Home Assistant code here is entirely original.

Original project:  
https://github.com/StephanJoubert/solarman

---

## 🧪 Hardware Used for Testing

All development and validation were performed using:

### ✔️ **Ebyte NA111-E Modbus TCP → RS485 gateway**  
Product page:  
https://www.cdebyte.com/products/NA111-E

This device was used to test:

- Modbus TCP communication  
- multi‑range polling  
- register decoding  
- stability and timing  
- compatibility with Deye Hybrid inverters  

### ✔️ **FTDI USB‑RS485 adapter (direct connection)**

The integration also works **without any gateway**, using a simple USB‑RS485 FTDI adapter connected directly to the inverter’s RS485 port.

This allows:

- direct Modbus RTU → Home Assistant communication  
- testing without network hardware  
- debugging register responses  
- validating wiring and polarity  

Both methods are fully supported.

---

## ⚠️ Deye lifetime-energy correction

Older releases decoded Solarman multi-register values with the 16-bit words in
the wrong order. Deye lifetime counters could consequently report millions of
kWh instead of hundreds. The correct Solarman convention lists the low word
first; for two registers the decoded value is:

```text
raw = low_word + (high_word × 65536)
```

The corrected parser also reads every register in a multi-register `rule: 1`
value instead of silently ignoring all but the first one.

### Home Assistant statistics migration

The integration deliberately does not rewrite Home Assistant's recorder or
long-term statistics. After upgrading, affected `total_increasing` entities
will drop from the old invalid value to the corrected inverter value. Home
Assistant treats that decrease as a new meter cycle, but previously recorded
states and statistic sums can still contain invalid energy.

Before upgrading, back up Home Assistant. After the first corrected poll,
review these entities under **Developer Tools → Statistics** and repair or
remove their invalid historical statistics as appropriate:

- Total Battery Charge
- Total Battery Discharge
- Total Energy Sold
- Total Load Consumption
- Total Production and Total Energy Bought if their high word was non-zero

Also verify any Energy Dashboard configuration that uses these entities. Do
not edit the recorder database directly without a tested backup and a separate
migration plan.

### SG05LP1 entity changes

Register `0x00A6` is signed AUX-port power, not a generator-connected Boolean.
The duplicate **Micro-inverter Power**, **Gen Power**, and invalid
**Gen-connected Status** entities are replaced by **AUX Port Power**. Register
`0x00C3` is a model-dependent status bitfield, so the incorrect 0/1
**SmartLoad Enable Status** is replaced by the diagnostic **AUX Status Raw**.
Update dashboards or automations that referenced the removed entity IDs.

### SG05LP1 SM2-P compatibility

The core telemetry and energy registers in
`deye-SG05LP1-EU-AM2-P-serie.yaml` were validated read-only on a
`SUN-6K-SG05LP1-EU-SM2-P`. The existing filename is retained because Home
Assistant config entries store it and the loader has no profile inheritance;
renaming it or adding a full duplicate would either break existing entries or
create two definitions that can drift. Model-dependent AUX/SmartLoad status
remains a raw diagnostic value until its individual bits are verified.

---

## 📌 Overview

**solarmodbus** is a fully local Home Assistant integration designed to read, decode, and expose Modbus TCP data from hybrid inverters compatible with the *Solarman* ecosystem.

Unlike cloud‑based Solarman solutions, this integration communicates **directly with the inverter over Modbus TCP**, providing:

- fast and stable updates  
- zero cloud dependency  
- no external accounts or API keys  
- full data ownership  
- multi‑brand support through YAML register definitions  

The integration uses a flexible architecture based on YAML files describing the Modbus register maps for each inverter brand/model. This makes it easy for the community to contribute additional definitions and expand compatibility.

---

## ✨ Features

- 🔌 **Direct Modbus TCP communication** (no cloud, no API keys)  
- ⚡ **Fast updates** with multi‑range polling  
- 🧩 **Multi‑brand architecture** (Deye, Sunsynk, LuxPower, Sofar…)  
- 📄 **YAML‑based register definitions**  
- 🔍 **Advanced parsing engine**  
  - endianness handling  
  - Solarman rule system  
  - bitmasks  
  - offsets  
  - string decoding  
  - multi‑register values  
- 🏠 **Native Home Assistant entities**  
- 🛠️ **Extensible by the community**  

---

## 🚧 Current Status

- ✔️ Fully working on **Deye Hybrid** (validated)  
- ✔️ Architecture ready for **multi‑brand support**  
- ⏳ Additional YAML definitions needed for other brands  
- 🤝 Community contributions welcome  

---

[📄 Solarmodbus Documentation (PDF)](./solarmodbus.pdf)

-    How to install on HAOS:

Just past this one-line on you ssh console:

`unzip -o <(curl -fsSL https://github.com/comdif/ha-solarmodbus/archive/refs/heads/main.zip) -d /tmp && cp -r /tmp/ha-solarmodbus-main/solarmodbus /config/custom_components/ && ha core restart`

-    How to install on other OS:

Just copy the solarmodbus directory in your HA custom-component directory.

-    How to install on ANY OS with an universal installer:

`bash <(curl -fsSL https://raw.githubusercontent.com/comdif/ha-solarmodbus/refs/heads/main/uinstall.sh) https://github.com/comdif/ha-solarmodbus/archive/refs/heads/main.zip`
