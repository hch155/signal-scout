## Tips for Optimal Signal Strength

<div class="justify-text">
Ensuring a strong and stable signal for your Customer Premise Equipment (CPE)'s antennas, Mi-Fi routers, phones can significantly improve your online experience. Here are some tips to help you align your equipment and maximize signal strength  
</div>

## Find the Nearest Base Station

<div class="justify-text">
Use the provided Google Maps link to locate nearest antenna sector.
Buy SIM card from one of the closest service provider, this ensures that you have the best signal strength & quality
Align your location with the azimuth of the nearest base station's antenna sector.
</div>

## Note on Environmental factors

<div class="justify-text">
In densely populated areas, be aware of potential signal reflections from buildings that can either enhance or weaken signal quality. 
The amount of background users, especially in busy hour can severly impact your user experience (achievable throughput), which in case of dense areas might require switching to different operator
</div>

## Avoiding Interference

<div class="justify-text">
Mind the distance from power lines to reduce Block Error Rate (BLER).
Be aware of physical obstructions that might block or reflect the signal.
</div>

## Optimize Equipment Placement

<div class="justify-text">
To maximize signal reflections ensure your equipment are correctly positioned to take advantage of MIMO (Multiple Input Multiple Output) setups, 
Perform multiple speed tests to find the best location for your equipment.
</div>

## Devices mode

<div class="justify-text">
NSA - Non-stand alone - current scenario - it is necessary for devices to first authenticate to 4G Network in order to attach 5G frequency

SA - Stand Alone - planned, can access the network directly to 5G Network
</div>

## To achieve best throughput it is recommended to test various component carriers & carrier aggregation
<div class="justify-text">

In Downlink (Base Station to User Equipment (UE)):

most devices support 4 carrier components in CA (carr   ier aggregation) in LTE mode only
when it comes to 5G mode, NSA, the devices support 1 LTE carrier + 2 NR carriers

In Uplink (UE to Base Station):

mostly devices support 1 or 2 carriers in Uplink

</div>

## Frequencies and bandwidths in Poland

<div class="justify-text">
Each operator has more or less similar network configuration:

LTE800 - b20 - 5MHz
LTE900 - b40 - 5MHz
LTE1800 - b3 - 15MHz
LTE2100 - b1 - 20MHz
LTE2600 - b7 - 20MHz
NR2100 (DSS - Dynamic Spectrum Sharing - shared with LTE2100) - 20MHz
NR3600 (C-band) - 100MHz

With 10MHz bandwidth and 256QAM modulation it is possible to achieve around 150Mbps in the best conditions (the closer to base station the better), in reality we can assume it will be around 100Mbps

device using LTE Mode only, 4 CA - LTE800 + LTE1800 + LTE2100 + LTE2600 = 60MHz, achieved DL throughput will be around 500-600Mbps, UL around 80Mbps
   
device in NSA mode, LTE2600 + NR3600 = 120MHz, DL resulting in total around 1000-1200Mbps, UL up to 150Mbps 

Most of the user equipment (minding their capabilities and network configuration priorities) tend to aggregate as most carriers as possible ensuring the best experience as possible.
</div>






