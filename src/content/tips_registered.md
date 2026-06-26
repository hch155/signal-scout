## Tips for Optimal Signal Strength

Ensuring a strong and stable signal for your Customer Premise Equipment (CPE) antennas, Mi-Fi routers, and phones can significantly improve your online experience. Here are some tips to help you align your equipment and maximize signal strength.

---

## Find the Nearest Base Station

- Use the provided Google Maps link to locate the nearest antenna sector
- Buy a SIM card from one of the closest service providers -- this ensures the best signal strength & quality
- Align your location with the azimuth of the nearest base station's antenna sector

---

## Note on Environmental Factors

- In densely populated areas, be aware of potential signal reflections from buildings that can either enhance or weaken signal quality
- The number of background users, especially during busy hours, can severely impact your user experience (achievable throughput), which in dense areas might require switching to a different operator

---

## Avoiding Interference

- Mind the distance from power lines to reduce Block Error Rate (BLER)
- Be aware of physical obstructions that might block or reflect the signal

---

## Optimize Equipment Placement

- To maximize signal reflections, ensure your equipment is correctly positioned to take advantage of MIMO (Multiple Input Multiple Output) setups
- Perform multiple speed tests to find the best location for your equipment

---

## Device Modes

<p><strong>NSA (Non-Standalone)</strong> -- current scenario -- devices must first authenticate to the 4G network in order to attach a 5G frequency carrier.</p>

<p><strong>SA (Standalone)</strong> -- planned deployment -- devices can access the 5G network directly without a 4G anchor.</p>

---

## Carrier Aggregation & Throughput

To achieve the best throughput, it is recommended to test various component carriers and carrier aggregation configurations.

**Downlink** (Base Station to User Equipment):

- Most devices support up to 4 carrier components in CA (Carrier Aggregation) in LTE mode
- In 5G NSA mode, devices typically support 1 LTE carrier + 2 NR carriers

**Uplink** (User Equipment to Base Station):

- Most devices support 1 or 2 carriers in uplink

---

## Frequencies and Bandwidths in Poland

Each operator's network configuration consists of similar component carriers:

| Band | 3GPP Band | Bandwidth |
|------|-----------|-----------|
| LTE800 | B20 | 5–10 MHz |
| LTE900 | B8 | 5 MHz |
| LTE1800 | B3 | 15 MHz |
| LTE2100 | B1 | 20 MHz |
| LTE2600 | B7 | 20 MHz |
| NR2100 (DSS) | n1 | 20 MHz |
| NR3600 (C-band) | n78 | 100 MHz |

> Width is the typical per-operator carrier and varies; e.g. LTE800 is 10 MHz on Orange/T-Mobile, 5 MHz on Play/Plus.

**Achievable throughput examples:**

- With 10 MHz bandwidth and 256QAM modulation: ~100-150 Mbps in optimal conditions
- **LTE-only** (4CA: LTE800 + LTE1800 + LTE2100 + LTE2600 = 60–65 MHz): DL ~500-600 Mbps, UL ~80 Mbps
- **5G NSA** (LTE2600 + NR3600 = 120 MHz): DL ~1000-1200 Mbps (peak 1500-1600 Mbps), UL ~150 Mbps

Most user equipment will aggregate as many carriers as possible for the best experience.

---

## Understanding Signal Strength and Quality

The metrics RSRP, RSRQ, and SINR are pivotal in evaluating signal strength and quality of cellular connections, applicable to both LTE and 5G networks.

### RSRP (Reference Signal Received Power)

The most basic measure of signal strength. A higher RSRP value indicates a stronger signal.

| Rating | RSRP Range |
|--------|------------|
| Excellent | > -80 dBm |
| Good | -80 to -90 dBm |
| Fair | -90 to -100 dBm |
| Poor | < -100 dBm |

### RSRQ (Reference Signal Received Quality)

Evaluates the quality of the received signal, considering both signal strength and interference levels. Especially useful in dense network environments.

| Rating | RSRQ Range |
|--------|------------|
| Excellent | > -10 dB |
| Good | -10 to -15 dB |
| Fair | -15 to -20 dB |
| Poor | < -20 dB |

### SINR (Signal-to-Interference-plus-Noise Ratio)

Compares the signal level to combined interference and noise. Higher values indicate a clearer, better quality signal.

| Rating | SINR Range |
|--------|------------|
| Excellent | > 20 dB |
| Good | 13 to 20 dB |
| Fair | 0 to 13 dB |
| Poor | < 0 dB |

Monitoring these metrics gives crucial insight into your cellular network's performance. Stronger RSRP and higher RSRQ/SINR values generally mean a more reliable and faster connection, essential for voice calls, streaming, and data services.

---

## Obtaining Cell Information from Your Device

By using the following codes, you can access the hidden diagnostic menu on your device:

- **iOS:** `*3001#12345#*`
- **Android:** `*#*#4636#*#*`

### iOS Field Test Mode

When you dial `*3001#12345#*` on an iOS device, it enters Field Test Mode. This hidden feature offers a deeper look into cellular connectivity. Key information available:

- **PLMN** (Public Land Mobile Network) -- identifies the mobile network (MCC + MNC). For example, 26006 = Poland, operator 06
- **Band Information** -- the specific frequency band your device is using
- **Bandwidth** -- width of the frequency band (MHz); wider bandwidth allows higher throughput
- **Cell ID** -- unique identifier for the cell tower; can be used to extract cell ID and base station ID
- **Radio Access** -- network technology in use (5G, LTE, etc.)
- **PCI** (Physical Cell ID) -- identifies a physical cell, crucial for handover and physical layer signaling
- **TAC** (Tracking Area Code) -- used for device tracking and paging procedures
- **EARFCN DL** -- specifies the downlink frequency channel number in LTE

### Key Signal Metrics

- **RSRP** (Reference Signal Received Power) -- primary indicator of signal strength
- **RSRQ** (Reference Signal Received Quality) -- assesses signal quality considering interference and noise
- **SINR** (Signal-to-Interference-plus-Noise Ratio) -- compares signal to background noise; higher is better
- **ConnectionStats** -- data rates, latency, packet loss, and other connection quality metrics
- **RACH Attempt** -- monitors device attempts to initiate a connection with the network via Random Access Channel
- **Serving Cell Info** -- details about the currently connected cell tower including all metrics above
