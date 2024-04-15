## Tips for Optimal Signal Strength


<p>Ensuring a strong and stable signal for your Customer Premise Equipment (CPE)'s antennas, Mi-Fi routers, phones can significantly improve your online experience</p>
<p>Here are some tips to help you align your equipment and maximize signal strength</p>


## Find the Nearest Base Station

<p>Use the provided Google Maps link to locate nearest antenna sector</p>
<p>Buy SIM card from one of the closest service provider, this ensures that you have the best signal strength & quality</p>
<p>Align your location with the azimuth of the nearest base station's antenna sector</p>

## Note on Environmental factors

<p>In densely populated areas, be aware of potential signal reflections from buildings that can either enhance or weaken signal quality</p>
<p>The amount of background users, especially in busy hour can severly impact your user experience (achievable throughput), which in case of dense areas might require switching to different operator</p>

## Avoiding Interference

<p>Mind the distance from power lines to reduce Block Error Rate (BLER)</p>
<p>Be aware of physical obstructions that might block or reflect the signal</p>


## Optimize Equipment Placement

<p>To maximize signal reflections ensure your equipment are correctly positioned to take advantage of MIMO (Multiple Input Multiple Output) setups</p>
<p>Perform multiple speed tests to find the best location for your equipment</p>

## Devices mode

<p>NSA - Non-stand alone - current scenario - it is necessary for devices to first authenticate to 4G Network in order to attach 5G frequency</p>

<p>SA - Stand Alone - planned, can access the network directly to 5G Network</p>


## To achieve best throughput it is recommended to test various component carriers & carrier aggregation

<p>In Downlink (Base Station to User Equipment (UE)):</p>

<p>- most devices support 4 carrier components in CA (carrier aggregation) in LTE mode only</p>
<p>- when it comes to 5G mode, NSA, the devices support 1 LTE carrier + 2 NR carriers</p>

<p>In Uplink (UE to Base Station):</p>

<p>- mostly devices support 1 or 2 carriers in Uplink</p>

## Frequencies and bandwidths in Poland

<p>Each operator's network configuration consists of more or less similar component carriers:</p>
<p>LTE800 - band 20 - 5MHz</p>
<p>LTE900 - b40 - 5MHz</p>
<p>LTE1800 - b3 - 15MHz</p>
<p>LTE2100 - b1 - 20MHz</p>
<p>LTE2600 - b7 - 20MHz</p>
<p>NR2100 (DSS - Dynamic Spectrum Sharing - shared with LTE2100) - 20MHz</p>
<p>NR3600 (C-band) - 100MHz</p>

<p>With 10MHz bandwidth and 256QAM modulation it is possible to achieve around 150Mbps in the best conditions (the closer to base station the better), in reality we can assume it will be around 100Mbps</p>

<p>Device using LTE mode only, on average can aggregate up to 4 component carriers - LTE800 + LTE1800 + LTE2100 + LTE2600 = 60MHz, achieved DL throughput will be around 500-600Mbps, UL around 80Mbps</p>
   
<p>Device in NSA mode, LTE2600 + NR3600 = 120MHz, DL throughput resulting on average around 1000-1200Mbps (peak 1500-1600Mbps), UL up to 150Mbps</p>

<p>Most of the user equipment (minding their capabilities and network configuration priorities) tend to aggregate as most carriers as possible ensuring the best experience as possible</p>


## Obtaining cell information from mobile device

<p>By using the following codes, you can access hidden menu on your devices: </p>
<p>iOS: *3001#12345#* </p>
<p>Android: *#4636#*#* </p>
<br>
<p><strong>Deep Diving into iOS Field Test Mode: *3001#12345#*</strong></p>

<p>When you dial <em>*3001#12345#*</em> on an iOS device, it enters what's known as the Field Test Mode. This hidden feature offers advanced users and technicians a deeper look into the inner workings of their device's cellular connectivity. Here's a breakdown of some of the key information that can be accessed through this mode and what it means:</p>

<ul>
    <li>RAT (Radio Access Technology) Serving Cell Info
        <ul>
            <li>PLMN (Public Land Mobile Network): Identifies the mobile network that your phone is currently connected to. It is comprised of the MCC (Mobile Country Code) and MNC (Mobile Network Code), uniquely identifying the country and the mobile network operator, respectively. For example, PLMN 26006 indicates an operator in country code 260 (Poland) with an operator ID of 06.</li>
            <li>Band Information: Refers to the specific frequency band your device is using for its cellular connection. Different bands have varying characteristics in terms of coverage and data speed.</li>
            <li>Bandwidth: Indicates the width of the frequency band used for the network connection, measured in MHz. A wider bandwidth can allow for higher data throughput.</li>
            <li>Cell ID: A unique identifier for the cell tower your device is currently connected to. This can be used to pinpoint the location of the tower and extract cell ID and base station ID.</li>
            <li>Radio Access: This shows the type of network technology in use, such as 5G, LTE, each with its own set of performance characteristics.</li>
            <li>PCI (Physical Cell ID): An identifier used in LTE networks to identify a physical cell. It's crucial for the handover process between cells and for signaling on the physical layer.</li>
            <li>TAC (Tracking Area Code): Used in LTE networks, this code helps in managing device tracking and paging procedures between different areas within the network.</li>
            <li>EARFCN DL (E-UTRA Absolute Radio Frequency Channel Number for Downlink): Specifies the frequency channel used for the downlink in LTE networks. It's a unique number representing the carrier frequency and helps in identifying the specific frequency used for cellular communication.</li>
        </ul>
    </li>
</ul>

<p><strong>Band</strong></p>
<p>The Band refers to a specific range of frequencies that cellular networks use to transmit and receive signals. Different bands have different properties in terms of coverage and penetration. For example, lower frequency bands (such as 700 MHz) offer better coverage and indoor penetration but may have lower data throughput compared to higher frequency bands (such as 2600 MHz), which offer higher data rates but have a shorter range and reduced building penetration.</p>
<p><strong>ConnectionStats</strong></p>
<p>ConnectionStats likely refers to statistics regarding the device's connection to the network. This can include data rates, latency, packet loss, and other metrics that indicate the quality and reliability of the network connection. These stats are crucial for diagnosing connection problems and optimizing network performance.</p>
<p><strong>RACH Attempt</strong></p>
<p>RACH (Random Access Channel) Attempt refers to the process by which a device attempts to initiate a connection with the network. When a device needs to establish a connection for a call or data session, it sends a signal on the RACH. The network then responds, allowing the device to move to a dedicated channel for communication. Monitoring RACH attempts can be important for identifying issues with network access in congested areas or with weak signal strength.</p>
<p><strong>RSRP, RSRQ, SINR</strong></p>
<p>These terms relate to the quality of the signal between the device and the network:</p>
<p>RSRP (Reference Signal Received Power): Measures the power of signals received from the cell. It's a primary indicator of signal strength.</p>
<p>RSRQ (Reference Signal Received Quality): Provides an assessment of the quality of the received signal. RSRQ takes into account both the signal strength (RSRP) and the level of interference and noise. It's particularly useful for evaluating performance in areas with high cell density.</p>
<p>SINR (Signal-to-Interference-plus-Noise Ratio): This metric compares the level of the signal to the background noise plus interference from other sources. A higher SINR indicates a better quality of connection, as it suggests that the signal is much clearer compared to the noise and interference.</p>
<p><strong>Serving Cell Info</strong></p>
<p>Serving Cell Info provides details about the cell tower (base station) to which the device is currently connected. This can include the cell ID, frequency band, technology (e.g., LTE, 5G), and various performance metrics like RSRP, RSRQ, and SINR mentioned above. This information is vital for understanding the current connection's characteristics and can help in troubleshooting connectivity issues or optimizing network performance.</p>
<p>Together, these metrics offer a comprehensive view of the device's interaction with the cellular network, highlighting areas of strength and pinpointing potential issues that could affect the user experience. Understanding these elements is key for network engineers, technicians, and enthusiasts who are keen on maximizing cellular network performance and reliability.</p>

## Understanding Signal Strength and Quality

<p>The metrics RSRP, RSRQ, and SINR are pivotal in evaluating the signal strength and quality of cellular connections, applicable not only to LTE but also to 5G networks. Understanding these can provide users with insight into the robustness of their signal connection.</p>
<p>RSRP is the most basic measure of signal strength. For LTE and 5G, a higher RSRP value indicates a stronger signal. Signal strength can be broadly categorized as follows:</p>
<ul>
    <li>Excellent Signal: RSRP higher than -80 dBm</li>
    <li>Good Signal: RSRP between -80 dBm and -90 dBm</li>
    <li>Fair Signal: RSRP between -90 dBm and -100 dBm</li>
    <li>Poor Signal: RSRP lower than -100 dBm</li>
</ul>
<p>RSRQ helps evaluate the quality of the received signal, considering both signal strength and interference levels. It is especially useful in dense network environments. For LTE and 5G:</p>
<ul>
    <li>Excellent Quality: RSRQ higher than -10 dB</li>
    <li>Good Quality: RSRQ between -10 dB and -15 dB</li>
    <li>Fair Quality: RSRQ between -15 dB and -20 dB</li>
    <li>Poor Quality: RSRQ lower than -20 dB</li>
</ul>
<p>SINR compares the level of the signal to the combined interference and noise. Higher SINR values indicate a clearer and better quality signal. Typical SINR ranges for a good user experience:</p>
<ul>
    <li>Excellent Quality: SINR higher than 20 dB</li>
    <li>Good Quality: SINR between 13 dB and 20 dB</li>
    <li>Fair Quality: SINR between 0 dB and 13 dB</li>
    <li>Poor Quality: SINR less than 0 dB</li>
</ul>
<p>Monitoring RSRP, RSRQ, and SINR metrics can give users crucial information about their cellular network's signal strength and quality. A stronger RSRP and higher RSRQ and SINR values generally mean a more reliable and faster network connection, which is essential for high-quality voice calls, streaming, and data services. By keeping an eye on these parameters, users can better understand their connectivity status and troubleshoot issues related to poor signal strength or quality.</p>







