# Randbetingelsesanalyse for EO-dampcelle v1

## Konklusjon

Den viktigste metrologiske forskjellen er mellom **statiske asymmetrier** og forhold som faktisk endrer EO-signalet:

- Statisk forskjell i RH, temperatur, lekkasje og sensor-nullpunkt kan gi svært store feil i en enkelt strømretning, men kanselleres i stor grad av en stabil polaritetsreversering.
- Ideell ABBA-rekkefølge kansellerer konstant og lineær tidsdrift. Resten – kurvatur, hysterese, polaritetskoblet settling og endringer mellom blokkene – kanselleres ikke. Denne residualen er den viktigste feilkilden for de lave EO-signalene i det deklarerte stressrommet.
- Gassfilm, kanalhøyde, støttestruktur og aktivt areal er fysiske transportledd. De kanselleres ikke ved polaritetsreversering og må karakteriseres eksperimentelt.
- En liten lukket, stiv celle får raskt endrede trykk- og fuktbetingelser. Den egner seg som transient demonstrator, ikke som et konstant-randbetingelse-forsøk.

Analysen bruker en 25 cm2 celle med 2 mm kanal på hver side, 32 °C, vannaktivitet 0,50, nominell hastighet 1 m/s og omtrent 6 L/min per side. Materialpunktene er scenarier, ikke målinger av en bestemt membran.

## Viktigste tall

For et grensefølsomt scenario med EO-drag lik 1 og høy diffusivitet fant modellen:

| Endring fra nominelt tilfelle | Enveis estimat | Polaritetsoddet estimat |
|---|---:|---:|
| +0,1 RH-prosentpoeng innløpsforskjell | +10,2 % | omtrent 0 % |
| +0,1 K sideforskjell | -28,9 % | omtrent 0 % |
| Kanalhøyde 2 til 1 mm | — | -2,0 % |
| Kanalhøyde 2 til 4 mm | — | -10,1 % |

Den nominelle netto EO-raten i dette scenarioet er 12,37 mg/h, mot 16,80 mg/h brutto Faraday-rate. Gassfilm og passiv tilbakediffusjon reduserer altså signalet til 73,6 % av bruttoverdien.

De kombinerte 95-prosentkvantilene er betinget på de valgte spennene i konfigurasjonen. De er **ikke** konfidensintervaller:

| Scenario | Nominell odd rate | 95-prosentkvantil av absolutt odd feil |
|---|---:|---:|
| Lavt drag, langsom diffusjon | 5,04 mg/h | 24,80 % |
| Drag 1, langsom diffusjon | 16,80 mg/h | 7,47 % |
| Drag 1, rask diffusjon | 12,37 mg/h | 16,98 % |
| Hypotetisk inversdesign-anker | 168,14 mg/h | 1,01 % |

For lavt og moderat signal dominerer den deklarerte residuale RH-forskjellen mellom polaritetsmålingene. For rask diffusjon dominerer usikker gassfilm, etterfulgt av denne RH-residualen. For det store inversdesign-signalet blir aktivt areal og strømkalibrering synlige. Dette er ikke en påstand om at lineær drift overlever ABBA; spennvidden må erstattes med den faktisk målte ABBA-residualen.

## Åpen kontra lukket drift

I en stiv, lukket celle er randbetingelsen en tilstand som utvikler seg:

- Et 5 mL gassvolum per side når 5 Pa differansetrykk på omtrent 0,063 s ved 5,04 mg/h i den rene gasskapasitetsgrensen.
- Et 5 L volum per side bruker omtrent 63,4 s i samme grense.
- En symmetrisk endring tilsvarende 1 RH-prosentpoeng på hver side gir omtrent 95 Pa damptrykksforskjell.
- Bare 0,1 K temperaturforskjell gir omtrent 33 Pa termisk trykkforskjell i en stiv celle.

Vegger, membran og pakninger kan lagre vann og forsinke responsen kraftig. Denne kapasiteten er foreløpig skjermet som 0–100 ganger gasskapasiteten og må identifiseres med RH-trinn på folieblank og montert membran.

## Foreslått forsøksdesign

1. Bruk én kondisjonert innløpsstrøm som splittes til begge sider.
2. Bruk `+I, -I, -I, +I` (ABBA), med nullstrømsperioder, og rapporter enveis, polaritetsjevn og polaritetsoddet rate separat.
3. Kryssbytt samme RH-referanse mellom kanalene. Spesifiser og mål residualen over én hel ABBA-blokk, ikke bare absolutt sensornøyaktighet. Speil eller randomiser blokkrekkefølgen for å avdekke kurvatur og hysterese.
4. Kjør 1, 2 og 4 mm gap og 0,5x, 1x og 2x strømning for å identifisere film/støtteeffekt.
5. Kjør folieblank og trykkutfordringer før og etter hver blokk.
6. Bruk 20 x 20, 8 x 50, 30 x 30, 40 x 40 og 50 x 50 mm åpninger. De tre opprinnelige kvadratene gir null residualfrihetsgrader for modellen `blank + areal + omkrets`. Det anbefalte fempunktsdesignet gir to residualfrihetsgrader og reduserer areal–omkrets-korrelasjonen fra 0,995 til 0,960. Kjør 8 x 50 mm-sporet både langs og på tvers av strømmen.
7. Bruk gjennomstrømningscellen som hovedmåling av EO-rate. Bruk den lukkede cellen til å tilpasse en transient massebalanse med EO og passiv tilbakediffusjon samtidig.

## Modellgrense

Modellen inkluderer finite gassfilmer, kortkanal-massebalanse, RH- og temperaturasymmetri, trykkdrevet bypass, kanttransport, areal- og strømfeil samt en deklarert ikke-kansellerende residual mellom polaritetsmålinger. Den inkluderer ikke en full tidsavhengig ABBA-modell, lokal todimensjonal strømning, kondensasjon eller vann produsert/forbrukt av elektrodereaksjoner. Disse må fortsatt kontrolleres i hardware og i gass-/ladningsbalansen.

## Kjøring

```bash
cd /home/torsheim/HeiQ/XMembrane_Trond_Study
python3 scripts/analyze_eo_vapor_boundaries_v1.py
python3 -m pytest -q -s tests/test_eo_vapor_boundary_analysis_v1.py tests/test_eo_vapor_test_cell_design.py
```

Inndata ligger i `config/eo_vapor_boundary_analysis_v1.json`. Resultattabeller, audit-fil og figurer skrives til `outputs/eo_vapor_boundary_analysis_v1/`.
