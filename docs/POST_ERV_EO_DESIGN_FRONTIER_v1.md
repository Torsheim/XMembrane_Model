# Videre designstudie: EO etter ERV

Dato: 2026-08-27

Studie-ID: `post-erv-eo-design-frontier-v1-2026-08-27`

Status: numerisk og proveniensmessig audit `PASS`

## Hva studien undersøker

Studien viderefører arkitekturen

```text
uteluft -> passiv ERV -> EO-polering -> resterende AC
```

og undersøker tre spørsmål:

1. Hvor stor del av den gjenværende latentlasten kan EO ta ved maksimalt 1 V?
2. Hvordan flytter energimessig beste EO-andel seg når receiver/sluk-SEC øker?
3. Kan mer receiverluft, tørrere receiverinnløp eller bedre filmtransport gjenopprette positiv lokal membranretning?

Prosentaksen er andel av den endelige fuktighetsdifferansen fra ERV-utløpet til
tilluftsmålet. `50 %` i denne studien er derfor ikke O50. Det absolutte O50-målet
er allerede nådd av ERV alene. O30 tilsvarer `72,700307 %` av restlasten.

## Designrom og påstandsgrense

Den balanserte primærgriden bruker bare tilgjengelig post-ERV-avkast som
receiverluft (`R=1`), fem diffusiviteter, strømmer fra 0,5 til 5 A/m² og en
arealgrense på 60 000 m². En adaptiv bisection finner 1 V-grensen uten
ekstrapolasjon.

Receiverdiagnostikken bruker fast ankermateriale og 3 A/m² ved 50, 60 og 70 %
samt O30. Den varierer:

- receiver/prosess-tørrluftsforhold `R = 1, 1,5, 2, 3`;
- receiverinnløp `RH = 0,20, 0,40, 0,45, 0,50, 0,60` og eksakt ERV-baseline;
- receiver-filmkoeffisient `0,5x, 1x, 2x, 5x`.

Disse inngrepene er diagnostiske. Kondisjonering, ekstra vifte/manifold,
receiverregenerering eller -disponering, varmeavvisning og elektrisk
eksport/topologi er ikke lukket. Receiverintervensjonene er derfor aldri
energirankbare, og `full_system_claim_allowed=false` i alle utdata.

## Auditresultat

| Populasjon | Caser | Nådde mål | Bestod deklarert gate | Positiv lokal retning |
|---|---:|---:|---:|---:|
| Balansert primærgrid | 1250 | 1005 | 1002 | 0 |
| Receiverdiagnostikk | 384 | 384 | 384 | 160 |

Alle fem valgte step-halving-caser bestod. Kildebildet var uendret under
kjøringen, foreldreproveniensen bestod, case-ID-dekningen var eksakt og alle 23
publiserte filer bestod etterfølgende manifest-/kontrakthashkontroll.

## 1 V-fronten

Den største samplede, balanserte EO-andelen ved eller under 1 V er brakket inn
til:

```text
76,328125 %  <=  1 V-fronten  <  76,406250 %
```

Brakettbredden er `0,078125` prosentpoeng. Det nedre punktet bruker
`D=1e-11 m²/s`, `j=0,75 A/m²`, 53 654,55 m² og 0,998786 V. Det øvre punktet
krever 53 771,08 m² og 1,000176 V. Fronten ligger dermed over O30, men svært
nær arealgrensen og med et lavt gjenværende receiver/sluk-budsjett.

### O30 ved og uten 1 V-krav

| O30-valg | D | j | Areal | Maks. V | Gevinst før receiver/sluk | Receiver/sluk-budsjett | Min. lokal margin |
|---|---:|---:|---:|---:|---:|---:|---:|
| Betinget energibest | 1,598e-14 | 3,00 | 6089,09 m² | 1,313690 V | 164,22 kW | 0,133702 kWh/kg | -0,303799 |
| Energibest ved <=1 V | 1,598e-14 | 0,75 | 24 369,97 m² | 0,985815 V | 144,90 kW | 0,117974 kWh/kg | -0,232696 |

O30 kan altså bringes under 1 V i det samplede griden. Prisen er omtrent fire
ganger membranarealet, 19,32 kW lavere gevinst før receiver/sluk og et redusert
receiver/sluk-SEC-budsjett. Den lokale overflateretningen er fortsatt negativ.

## Energifunn når EO-andelen økes

Tabellen viser beste punkt innen det samplede, balanserte `<=1 V`-vinduet.
Receiver/sluk-SEC er en parameterisert kostnad, ikke en validert komponentmodell.

| Receiver/sluk-SEC | Beste andel i vinduet | Betinget gevinst |
|---:|---:|---:|
| 0,000 kWh/kg | 67,5 % | 148,60 kW |
| 0,050 kWh/kg | 67,5 % | 91,58 kW |
| 0,100 kWh/kg | 62,5 % | 36,14 kW |
| 0,125 kWh/kg | 55,0 % | 11,12 kW |
| 0,130 kWh/kg | 50,0 % | 6,64 kW |
| 0,135 kWh/kg | 50,0 % | 2,42 kW |
| 0,140 kWh/kg | 50,0 % | -1,81 kW |
| 0,150 kWh/kg | 50,0 % | -10,25 kW |

Hovedfunnene er:

- Mer EO er ikke automatisk mer energisparing når 1 V tvinger strømmen ned og
  arealet opp.
- Ved lav receiver/sluk-SEC topper den samplede 1 V-kurven rundt 67,5 %, ikke
  ved selve spenningsfronten.
- Ved 0,10 kWh/kg flyttes toppen til 62,5 %, og ved 0,125 kWh/kg til 55 %.
- Ved 0,14 kWh/kg er alle undersøkte punkter fra 50 % og oppover energitap.
- O30s `<=1 V`-case er positiv ved receiver/sluk-SEC 0,10 kWh/kg
  (`22,08 kW`), men negativ ved 0,125 kWh/kg (`-8,63 kW`). Dets lokale
  break-even-budsjett er 0,117974 kWh/kg.

«Beste» betyr bare beste punkt i det undersøkte vinduet og under den oppgitte
modellgrensen. Det er ikke et validert fullsystemoptimum.

## Membran- og receiverfunn

Med balansert ERV-avkast har alle 1250 primærcasene negativ lokal
kilde-minus-receiver-overflatemargin. Mer receiverluft alene reduserer
receiveraktiviteten, men gjenoppretter ikke retningen. Filmforbedring alene gjør
heller ikke det.

Tørrere receiverluft gir følgende interpolerte nullmarginer ved `R=1`, 3 A/m²
og baseline filmkoeffisient:

| EO-andel | Receiverinnløp-RH ved null lokal margin |
|---:|---:|
| 50 % | 0,489133 |
| 60 % | 0,455651 |
| 70 % | 0,422106 |
| O30 / 72,7003 % | 0,413122 |

Det avgjørende forbeholdet er elektrisk: alle 160 receiverdiagnoser med positiv
lokal margin hadde `negative_voltage_everywhere`. De beskriver derfor en
passiv-gradient/generator-sign-situasjon, ikke dokumentert ordinær EO-importdrift.
Ingen undersøkt receiverintervensjon kombinerte positiv lokal retning med
ikke-negativ terminalspenning over hele arealet.

## Kjøring og sentrale filer

```bash
python3 -B scripts/make_post_erv_eo_design_frontier_v1.py \
  --smoke --jobs 4 \
  --output-dir outputs/post_erv_eo_design_frontier_v1_smoke --overwrite

python3 -B scripts/make_post_erv_eo_design_frontier_v1.py \
  --jobs 8 \
  --output-dir outputs/post_erv_eo_design_frontier_v1 --overwrite

TMPDIR=/tmp pytest -q -s \
  tests/test_post_erv_eo_design_frontier_v1.py \
  tests/test_post_erv_eo_percentage_sweep_v1.py \
  tests/test_post_erv_full_eo_study_v1.py
```

Sentrale utdata:

- `outputs/post_erv_eo_design_frontier_v1/audit.json`
- `outputs/post_erv_eo_design_frontier_v1/selected_primary_cases.csv`
- `outputs/post_erv_eo_design_frontier_v1/one_volt_frontier_trace.csv`
- `outputs/post_erv_eo_design_frontier_v1/receiver_sink_energy_scenarios.csv`
- `outputs/post_erv_eo_design_frontier_v1/receiver_surface_direction_thresholds.csv`
- `outputs/post_erv_eo_design_frontier_v1/receiver_intervention_cases.csv`
- `outputs/post_erv_eo_design_frontier_v1/output_manifest.json`
