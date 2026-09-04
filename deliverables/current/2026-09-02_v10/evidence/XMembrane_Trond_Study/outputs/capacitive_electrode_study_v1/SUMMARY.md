# Capacitive-electrode transient study v1

## Main finding

A purely blocking capacitive electrode pair does not support the continuous DC current assumed by the earlier steady model. It gives a finite startup displacement while the electrodes charge; after the 1.8 V limit is reached, current and incremental EO transport decay toward zero.

For the 25 cm² cell and the unmeasured reference assumption of 10,000 F/m² for each identical electrode (5,000 F/m² effective pair capacitance):

- At 0.5 A/m², the capacitive model retains 100.0% of the counterfactual continuous-electrode EO displacement after 1 h, but only 20.8% when averaged over 24 h.
- At 1 A/m², the corresponding values are 100.0% and 10.4%.
- At 5 A/m², they fall to 49.7% after 1 h and 2.1% over 24 h.
- The ideal blocking case ends at 4.441e-14 A/m² after 24 h.

## Symmetric cycling

The full-cycle EO increment is zero to numerical precision for the reference sweep (maximum |cycle EO| 0 mg and maximum charge-closure residual 1.11e-08 C/m²). Water is moved forward during one half-cycle and returned during the other. The assisting ERV gradient retains its passive diffusion contribution, but it does not make constant-drag, charge-balanced EO transport sustainable by itself.

## Interpretation

A nonzero sustained result in the leakage sweep comes from the diagnostic Faradaic leakage branch. It must therefore be treated as an electrode-reaction architecture, with reaction products, lifetime and overpotential measured explicitly—not as purely capacitive EO.

## Dual frozen replay of the stored direct-ERV cases

The primary same-boundary replay retains the original stored terminal-voltage limits (0.025 V for O30 and 0.25 V for full duty). At O30 it retains 16.2% of the former steady EO displacement over the first hour and 0.68% when averaged over 24 h.
For the full-duty case, the primary values are 16.5% and 0.69%. The corresponding finite inventories are 0.17 h and 0.17 h at the original target rates.
The separate optimistic sensitivity keeps commanding the stored current densities and permits terminal voltage to rise to 1.8 V. It gives O30 retentions of 98.5% and 4.6%, and full-duty retentions of 92.3% and 5.0%, at 1 h and 24 h. These are upper-bound sensitivities, not same-voltage replays.

Both modes freeze the original bulk states, films and installed area while current collapses. They diagnose duration only; neither is a mass-balanced transient ERV or a revised HVAC-saving calculation.
The model reports an effective pair-capacitor voltage but does not resolve or constrain individual electrode potentials or impose an electrode-pair electrochemical stability window. In the 1.8 V O30 upper-bound replay the maximum pair-capacitor voltage is 2.25 V; the 1.8 V terminal ceiling must not be read as an electrode-window limit.

## Claim boundary

The electrical RC state is transient, but the membrane profile is still quasi-steady. The anchor membrane has L²/D ≈ 23.69 h, so the tested AC periods are faster than internal water equilibration and are not frequency-validated predictions. Capacitance, leakage, ESR and energy recovery are sensitivity coordinates, not measurements. Gas-stream humidity response, dynamic axial ERV evolution, CPE dispersion, individual electrode potentials, electrode stability windows and full-system energy are not closed.
