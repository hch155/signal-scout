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







