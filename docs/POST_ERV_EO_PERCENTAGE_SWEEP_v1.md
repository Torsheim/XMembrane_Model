# Økende EO-andel etter passiv ERV

Denne studien viser hva som skjer når EO tar en stadig større del av den
gjenværende avfuktingen etter den passive ERV-en. Hovedbildet er todelt:
Den betingede energigevinsten øker med EO-andelen så lenge den samlede
EO-energien per transportert kilogram vann er lav nok, men samtidig øker
membranareal, terminalspenning og receiverbelastning. Resultatene definerer
derfor et teknisk og energimessig vindu; de dokumenterer ikke et validert
fullsystemoptimum.

Studien er reproduserbar fra
`scripts/make_post_erv_eo_percentage_sweep_v1.py`. De deklarerte aksene ligger
i `config/post_erv_eo_percentage_sweep_v1.json`, og det ferdige, auditerte
resultatsettet ligger i `outputs/post_erv_eo_percentage_sweep_v1`.

## Systemet som er analysert

```text
uteluft -> passiv ERV -> EO -> nedstrøms kjølebatteri -> tilluft
                         |
                         +-> receiver/avkast og uløst vann-/varmesluk
```

EO kommer altså **etter ERV**. ERV-en leverer 23,00 °C og
13,215 g vann/kg tørrluft. EO senker deretter absolutt fuktighet mot
tilluftsmålet på 7,260 g/kg. For alle punkter under nøyaktig 100 % håndterer
kjølebatteriet resten av den latente lasten i screeningmodellen. Ved det
nøyaktige 100 %-punktet har EO nådd tilluftens fuktighetsforhold, og batteriet
går over til den idealiserte rent sensible grenen.

## To forskjellige prosentdefinisjoner

Det tidligere «10 %»-resultatet og den nye prosentaksen har ikke samme nevner.
Studien beholder derfor begge koordinatene eksplisitt:

```text
historisk relativ reduksjon = 100 * (w_ERV - w_mål) / w_ERV

fullført restlast = 100 * (w_ERV - w_mål) / (w_ERV - w_tilluft)
```

Den nye hovedaksen er **fullført restlast**, fordi 0 % da betyr ingen EO etter
ERV og 100 % betyr at EO tar hele den endelige ERV-til-tilluft-lasten. Det
historiske 10 %-caset reduserte derimot fuktighetsforholdet med 10 % relativt
til selve ERV-utløpet. Det tilsvarer **22,1925 % av den endelige restlasten**,
ikke 10 % på den nye aksen. Dette forklarer hvorfor den tidligere analysen tok
utgangspunkt i «10 %»: det var den daværende, relative målformuleringen og
ikke en påstand om at 10 % var optimalt.

| Punkt | Fullført restlast | Historisk reduksjon | EO-mål | Vannplikt |
|---|---:|---:|---:|---:|
| 10 % på ny hovedakse | 10,0000 % | 4,5060 % | 12,620 g/kg | 168,95 kg/h |
| Historisk «10 %» | 22,1925 % | 10,0000 % | 11,893 g/kg | 374,94 kg/h |
| Halv restlast | 50,0000 % | 22,5301 % | 10,238 g/kg | 844,75 kg/h |
| O30 | 72,7003 % | 32,7590 % | 8,886 g/kg | 1228,27 kg/h |
| Hele restlasten | 100,0000 % | 45,0603 % | 7,260 g/kg | 1689,50 kg/h |

O30 er dermed et reelt mellompunkt, og tilsvarer 72,7003 % fullført restlast.
O50 er allerede passert før EO: O50 ved 32 °C er 14,952 g/kg, mens luften etter
ERV allerede er tørrere, 13,215 g/kg. Det finnes derfor ingen positiv
post-ERV EO-plikt for å nå O50 i dette systemet.

## Energitrenden når prosenten økes

Referansen med samme tilluftsleveranse er passiv ERV pluss konvensjonell AC,
543,741 kW totalt. Den gjenværende AC-effekten etter ERV er 509,381 kW.

Under det eksakte 100 %-endepunktet blir den sparte kjøleeffekten tilnærmet
proporsjonal med transportert vann i dagens mettede coil-gren. Med null
EO-varme til prosessluften blir den konservative gevinsten derfor omtrent
lineær med fullført restlast:

- samlet EO-SEC under 0,1567 kWh/kg gir økende gevinst når andelen økes;
- ved omtrent 0,1567 kWh/kg er hvert ekstra trinn tilnærmet energinøytralt;
- over 0,1567 kWh/kg gir en større EO-andel et stadig større energitap.

Tabellen viser konservativ besparelse mot ERV+AC-referansen ved tre antatte
**samlede** EO-SEC-verdier og null varmelekkasje til prosessluften:

| Fullført restlast | 0,050 kWh/kg | 0,100 kWh/kg | 0,150 kWh/kg |
|---|---:|---:|---:|
| Historisk «10 %» = 22,1925 % | 40,01 kW | 21,26 kW | 2,51 kW |
| 50 % | 90,14 kW | 47,90 kW | 5,66 kW |
| O30 = 72,7003 % | 131,06 kW | 69,64 kW | 8,23 kW |
| 100 %, konservativ kontrollgren | 180,27 kW | 95,80 kW | 11,32 kW |

Dette er grunnen til at det ikke finnes ett ubetinget svar på om mer EO sparer
eller taper energi. Retningen bestemmes av all-in SEC, inkludert de delene som
ennå ikke er fysisk lukket.

### Det eksakte 100 %-punktet er en egen kontrollgren

Nøyaktig ved 100 % skifter screeningmodellen fra en mettet coil-gren til
rent sensibel kjøling. Den eksakte, idealiserte break-even-verdien blir da
0,2752 kWh/kg, mot 0,1567 kWh/kg ved et vilkårlig lite avvik over
fuktighetsmålet. Ved 0,100 kWh/kg og null prosessvarme gir det eksakte punktet
295,99 kW beregnet besparelse, mens den konservative kontrollgrenen gir
95,80 kW. Det auditerte spranget er 200,20 kW.

Dette spranget skal ikke tolkes som en glatt fysisk bonus ved den siste
promillen av avfuktingen. Det er en diskret egenskap ved dagens coil- og
kontrollmodell. Inntil en reell coilsekvens rundt duggpunkt og settpunkt er
validert, er 0,1567 kWh/kg og den ensidige nær-endepunktsgrenen det
konservative beslutningsgrunnlaget. Det eksakte 100 %-resultatet rapporteres
separat og kobles ikke kontinuerlig til prosentkurven.

## Membran- og receivertrend

Den mest informative sammenligningen følger samme material- og
driftskoordinater hele veien: vanndiffusivitet 1,598e-14 m²/s,
strømtetthet 3,0 A/m² og receiver/prosess-luftforhold 1,0. Aktivt areal blir
dimensjonert på nytt ved hvert mål. Dette er derfor en **fast-koordinat
dimensjoneringstrajektorie**, ikke responsen til én allerede installert modul.

| Punkt | Aktivt areal | Maks. terminalspenning | Maks. receiver-overflateaktivitet | Min. drivmargin | Kjent kjerne+vifte-SEC | Konservativt receiver-/slukbudsjett |
|---|---:|---:|---:|---:|---:|---:|
| Historisk «10 %» | 1858,5 m² | 0,503 V | 0,8056 | -0,1351 | 0,01402 kWh/kg | 0,14268 kWh/kg |
| 50 % | 4187,5 m² | 0,917 V | 0,8681 | -0,2278 | 0,01884 kWh/kg | 0,13786 kWh/kg |
| O30 | 6089,1 m² | 1,314 V | 0,9189 | -0,3038 | 0,02300 kWh/kg | 0,13370 kWh/kg |
| 90 % | 7538,4 m² | 1,666 V | 0,9575 | -0,3620 | 0,02635 kWh/kg | 0,13035 kWh/kg |
| Hele restlasten | 8376,2 m² | 1,895 V | 0,9797 | -0,3957 | 0,02838 kWh/kg | 0,12832 kWh/kg |

Når EO-andelen økes, vokser arealet omtrent med vannplikten, mens både
terminalspenning og receiveraktivitet stiger. Receiveren beveger seg nærmere
metning, og den lokale overflatedrivmarginen blir mer negativ. Ingen av de
720 transportcasene beholdt positiv lokal overflatedrivretning gjennom hele
modulen. Dette er den viktigste fysiske advarselen i studien: den deklarerte
transport-/receivergaten kan passeres samtidig som den strengere lokale
drivretningstesten feiler.

Det konservative receiver-/slukbudsjettet er differansen mellom 0,1567 kWh/kg
og kjent EO-kjerne- og modulvifte-SEC for den valgte banen. Budsjettet krymper
fra 0,14268 kWh/kg ved det historiske punktet til 0,12832 kWh/kg ved full
restlast. Dersom receiverregenerering, vanndisponering, varmeavvisning og
øvrige manglende ledd samlet bruker mer enn dette, forsvinner den konservative
besparelsen. Lavere forbruk enn budsjettet er nødvendig, men ikke i seg selv
tilstrekkelig for å validere systemet.

## Sweep-resultat og numerisk audit

Den fulle transportmatrisen består av 12 prosentmål, fire diffusiviteter og
15 samplede strømtettheter ved balansert receiverforhold 1,0:

- 720 transportcaser ble kjørt uten transportunntak;
- 306 nådde det numeriske fuktmålet;
- 289 passerte deklarert transport- og receiver-overflategate;
- 0 beholdt positiv lokal overflatedrivretning overalt;
- alle 12 prosentmål hadde en tilgjengelig balansert primærseleksjon;
- 12 av 12 unike primær-/fast-koordinatcaser besto step-halveringskontrollen.

Strømtetthet er en samplet kontrollkoordinat, ikke en påstått
materialakseptgrense. Receiverforholdet er holdt eksakt på 1,0 slik at
primærresultatene bruker den balanserte ERV-avkaststrømmen og ikke skjuler en
ekstern receiverressurs.

`audit.json` har samlet `pass: true`, energibalansen lukker til
1,14e-13 kW i maksimal absolutt feil, og vann- og receiverbalansene lukker til
henholdsvis 3,21e-14 og 3,03e-15 relativ feil.

## Påstandsgrense

Alle energitall er betingede screeningresultater. `full_system_claim_allowed`
er `false`, og fullsystemstatus er `UNKNOWN` overalt. Følgende ledd er fortsatt
manglende eller parameteriserte:

- receiverregenerering eller disponering av transportert vann;
- receiverens varmeavvisning;
- konjugert termisk tilbakekobling mellom membran og luftstrømmer;
- rangerbart modul- og manifoldtrykkfall samt reell regulering;
- elektroder, holdbarhet, produksjon og praktisk modularkitektur.

Resultatet støtter derfor videre utforskning av høyere EO-andel, særlig dersom
receiver-/sluk-SEC kan holdes under det fallende budsjettet. Det støtter ikke
ennå at 100 %, O30 eller et annet prosentmål er et realisert eller optimalt
fullsystem.

## Viktigste artefakter

- `percentage_summary.csv`: samlet energi-, membran- og receivertrend per mål;
- `selection_status.csv`: eksplisitt status for alle 12 transportmål;
- `fixed_coordinate_sizing_trajectory.csv`: fast D/j/R-bane med nytt areal per mål;
- `percentage_energy_window.csv` og `percentage_break_even.csv`: tett energikurve;
- `receiver_and_sink_sec_scenarios.csv`: parameterisert receiver-/sluk-SEC;
- `selected_power_ledger.csv`: kjent og ukjent effekt per utvalgt case;
- `percentage_energy_saving.png`, `percentage_membrane_receiver.png` og
  `percentage_sec_budget.png`: hovedfigurene;
- `transport_contract.json` og `audit.json`: proveniens, kontrakt og maskinell audit.

## Kjøring

Kjør fra repository-roten:

```bash
# Rask, tett energikurve uten membransweep
python3 -B scripts/make_post_erv_eo_percentage_sweep_v1.py \
  --energy-only \
  --output-dir outputs/post_erv_eo_percentage_sweep_v1_energy_only \
  --overwrite

# Kort transport-smoke ved sju representative prosentmål
python3 -B scripts/make_post_erv_eo_percentage_sweep_v1.py \
  --smoke --jobs 4 \
  --output-dir outputs/post_erv_eo_percentage_sweep_v1_smoke \
  --overwrite

# Hele 720-case-studien
python3 -B scripts/make_post_erv_eo_percentage_sweep_v1.py \
  --jobs 8 \
  --output-dir outputs/post_erv_eo_percentage_sweep_v1 \
  --overwrite

# Regenerer tabeller, utvalg og figurer fra kontraktmatchet transport-CSV;
# utvalgte step-halveringscaser kjøres fremdeles på nytt
python3 -B scripts/make_post_erv_eo_percentage_sweep_v1.py \
  --postprocess-existing \
  --output-dir outputs/post_erv_eo_percentage_sweep_v1 \
  --overwrite

# Test prosentdefinisjoner, energigren, seleksjon, kontrakt og audit
pytest -q -s tests/test_post_erv_eo_percentage_sweep_v1.py
```

`--overwrite` erstatter studiens navngitte artefakter, mens
`transport_contract.json` binder transportresultatet til eksakt case-design,
konfigurasjon, generator, analyzer og modellkilder. Bruk `audit.json` som
maskinlesbar pass/fail-kilde og `SUMMARY.md` som kortversjon av funnene.
