# Volumscreen for netto transienttransport

Dette er en separat sensitivitetsstudie. Den endrer ikke det eksisterende
500 mL-konseptet eller påstår at en lukket celle måler intrinsisk EO-fluks.
Den sammenligner i stedet kalibrerte nettovolumer når RH-endringen er selve
nettotransportsignalet.

## Fast grunnlag

- Aktiv membran: 50 x 50 mm = 25 cm² i en 80 x 80 mm kupong.
- Lokalt membrangap: 2 mm; bulkdybde: 20 mm.
- Betinget målfluks: 208 g/m²/h, som over 25 cm² er 0.144444 mg/s.
- Over ett 5 s trinn flyttes 0.722222 mg vann.
- Geometrien reserverer 22,6 mL for komponenter og 21,9 mL kalibreringstrim ved denne konservative komponentgrensen.

## Beregninger

For hvert kalibrert nettovolum brukes

```text
V_gross = V_net + V_komponentgrense + V_trimreserve
side = sqrt(1000 V_gross / bulkdybde)
ΔRH = m_overført / (rho_sat V_net)
Δp_rigid = 2 (m_overført / M_vann) R T / V_net
```

`Δp_rigid` er en diagnose for helt stive, lukkede kamre. Den er ikke en
akseptabel driftsgrense; den viser hvorfor differansetrykk må måles og
utjevnes.

| Case | Nettovolum per side mL | Kvadratisk bulkfotavtrykk mm | RH-endring per trinn pp | Stiv Δp Pa | Tid til 10 pp s | SHT45-respons ved 10 pp |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Kompakt transientcelle | 200 | 110.6 | 10.69 | 1017 | 4.68 | 68.9% |
| Mellomvolum | 300 | 131.2 | 7.13 | 678 | 7.02 | 82.7% |
| Lavdriftcelle | 500 | 165.0 | 4.28 | 407 | 11.69 | 94.6% |

## Tolkning

Den kompakte løsningen gir tydeligst RH-signal, men også raskest utvikling av
damptrykks- og fuktgradienter. Den store løsningen gir roligere utvikling og
passer bedre til en langsom RH-sensor, men krever det brede plenumet. Alle tre
tilfellene forutsetter at blanding, lekkasje, temperaturbias og
differansetrykk verifiseres. Den tallfrie figuren er laget for presentasjon;
`volume_cases.csv` er den autoritative talltabellen.

For netto transienttransport er 200–300 mL et relevant kompakt område hvis en raskere RH-/duggpunktsreferanse brukes. Med SHT45 som hovedsensor er 500 mL og omtrent 12 s mer konsistent med sensorens respons.
