# ERV først, EO for hele den resterende avfuktingen

Denne studien tester arkitekturen brukeren beskrev: uteluften går først gjennom
en passiv ERV, og EO fjerner deretter all gjenværende fukt ned til samme
absolutte fuktighet som tilluftsmålet ved 20 °C og 50 % RH. Nedstrøms kjølebatteri
skal da bare dekke sensibel kjøling i det idealiserte endepunktet.

Studien er reproduserbar fra
`scripts/make_post_erv_full_eo_study_v1.py`, med alle akser og
referanseverdier deklarert i `config/post_erv_full_eo_study_v1.json`.

## Systemrekkefølge og mål

```text
uteluft -> passiv ERV -> EO -> sensibelt kjølebatteri -> tilluft
                         |
                         +-> receiver/avkast og uløst vann-/varmesluk
```

Den passive ERV-en leverer 23,00 °C og 13,215 g vann/kg tørrluft. EO-målet for
full restavfukting er 7,260 g/kg, som gir 1689,50 kg/h vanntransport ved
78,813 kg tørrluft/s.

O50 er ikke et post-ERV avfuktingsmål: O50 ved 32 °C tilsvarer 14,952 g/kg,
mens luften allerede er tørrere enn dette etter ERV. O30, 8,886 g/kg, er et
relevant mellompunkt.

## Energivinduer

Referansen med samme leveranse er passiv ERV pluss konvensjonell AC, totalt
543,741 kW. Av dette er 509,381 kW gjenværende AC etter ERV.

| EO-mål etter ERV | Vannplikt | Break-even all-in EO-SEC |
|---|---:|---:|
| 10 % reduksjon | 374,94 kg/h | 0,1567 kWh/kg |
| O30 | 1228,27 kg/h | 0,1567 kWh/kg |
| Hele restlasten, eksakt endepunkt | 1689,50 kg/h | 0,2752 kWh/kg |

For hele restlasten faller break-even fra 0,2752 til 0,2520 og
0,2324 kWh/kg når henholdsvis 0, 50 og 100 % av EO-varmen belaster
prosessluften.

Det høye 0,2752-resultatet gjelder bare nøyaktig ved fuktighetsmålet, der
screeningmodellen skifter til et rent sensibelt kjølebatteri. Et vilkårlig
lite avvik over målet sender modellen tilbake til en mettet latent
coil-gren og gir 0,1567 kWh/kg. Inntil en virkelig coil- og kontrollsekvens
er validert, bør 0,1567 kWh/kg brukes som det konservative budsjettet.

## Membran- og O50-resultater

Den finite-film, motstrøms membranberegningen varierer strømtetthet,
vanndiffusivitet og receiver/prosess-luftforhold. Strømtetthet er en
samplet koordinat, ikke en akseptgrense. Receiverforhold over 1,0 er kun en
kapasitetsfølsomhet fordi ekstra receiverluft og dens vifte-, kondisjonerings-
og disponeringsenergi ikke er modellert.

Av 480 caser nådde 195 det numeriske målet, og 185 passerte den deklarerte
transport- og receiver-overflategaten. Ingen beholdt positiv lokal
overflatedrivretning gjennom hele modulen. Dette er den sentrale fysiske
begrensningen i dagens modell.

Primærcasen for full restlast bruker bare den tilgjengelige balanserte
ERV-avkaststrømmen:

- diffusivitet 1,598e-14 m²/s og 3,0 A/m²;
- aktivt areal 8376,25 m²;
- terminalspenning 0,881–1,895 V;
- kjent EO-gridkraft 36,55 kW;
- idealiserte prosess- og receivervifter 11,40 kW totalt;
- kjent EO-kjerne pluss vifte-SEC 0,02838 kWh/kg;
- betinget gevinst før receiver-/slukenergi: 417,00 kW på det eksakte
  endepunktet og 216,80 kW på den konservative kontrollgrenen;
- gjenstående konservativt receiver-/slukbudsjett: 0,12832 kWh/kg;
- maksimal receiver-overflateaktivitet 0,9797, men minimum lokal
  drivmargin er negativ, -0,3957.

Casen består en 2 V-følsomhet, men ikke 1 V. En receiver-rate på 3,0 gir en
noe bedre kapasitetsdiagnostikk, men krever dobbelt så mye ekstra receiverluft
som den balanserte ERV-avkasten og er derfor ikke valgt som primærcase.

## Tolkning og åpne ledd

Resultatet viser at ERV først og EO for hele restlasten er energimessig verdt
å utforske videre. Det demonstrerer ikke at dagens membran eller receiver kan
realisere arkitekturen. Receiver-regenerering eller disponering, varmeavvisning,
termisk tilbakekobling, reelt manifoldtrykkfall, elektroder, holdbarhet og
produksjon er fortsatt uløst eller parameterisert. Manglende energiledd blir
ikke satt lik null, og alle fullsystemkrav er derfor eksplisitt `UNKNOWN`.

## Kjøring

Fra repository-roten:

```bash
# Rask energiberegning uten membransweep
python3 -B scripts/make_post_erv_full_eo_study_v1.py \
  --energy-only --output-dir outputs/post_erv_full_eo_energy_only_v1 --overwrite

# Kort transport-smoke
python3 -B scripts/make_post_erv_full_eo_study_v1.py \
  --smoke --jobs 4 --output-dir outputs/post_erv_full_eo_smoke_v1 --overwrite

# Hele 480-case-studien
python3 -B scripts/make_post_erv_full_eo_study_v1.py \
  --jobs 8 --output-dir outputs/post_erv_full_eo_study_v1 --overwrite

# Regenerer tabeller, utvalg og figurer uten full sweep;
# de sju utvalgte step-halveringscasene kjøres på nytt
python3 -B scripts/make_post_erv_full_eo_study_v1.py \
  --postprocess-existing --output-dir outputs/post_erv_full_eo_study_v1 --overwrite

# Test kontrakt, energivindu, balanser og transportanker
pytest -q -s tests/test_post_erv_full_eo_study_v1.py
```

`--overwrite` tillater bare at studiens navngitte artefakter erstattes; skriptet
sletter ikke ukjente filer i outputmappen. `transport_contract.json` binder
transporttabellen til eksakt case-design, config, generator, analyzer og
modellkilder. Se `audit.json` for maskinlesbar pass/fail og balansefeil.
