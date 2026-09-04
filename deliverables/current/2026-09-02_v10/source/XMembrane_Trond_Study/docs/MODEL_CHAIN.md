# Canonical model chain

## Current numerical hierarchy

```text
Local membrane transport (V2)
        |
        v
Axial process integration (V3)
        |
        v
Coupled process/receiver integration (V12.1)
        |
        v
Material + operating-point optimisation
        |
        +--> Bottleneck diagnostics
        |
        +--> Direct-liquid receiver
                    |
                    v
             Liquid-activity crossover
```

## 1. Local membrane transport

Canonical implementation:
`heiq_pre_receiver_material_analyses/heiq_pre_receiver_model.py`

This level solves local electro-osmotic and diffusive water transport, ionic conduction, activity-dependent material properties, reciprocal water-activity voltage, and voltage-controlled membrane states.

## 2. Axial process model

Canonical implementation:
`scripts/make_wp1_pre_receiver_axial_v3.py`

The process stream is integrated along cumulative active membrane area, with the local membrane problem re-solved at every area step.

## 3. Coupled two-stream receiver model

Canonical implementation:
`scripts/make_wp1_closed_receiver_system_v12.py`

Both process and receiver streams evolve axially and the same transported water closes both stream mass balances.

## 4. Material and operating-point optimisation

Canonical implementation:
`scripts/make_wp1_prearchitecture_continuation_v2.py`

This workflow performs O30 and O50 operating-point studies, receiver-flow optimisation, material screening, voltage refinement, and surface-state auditing.

## 5. Bottleneck diagnostics

Canonical implementation:
`scripts/make_wp1_prearchitecture_bottleneck_diagnostics_v1.py`

This workflow evaluates voltage decomposition, EO versus diffusion flux, gas-film sensitivity, receiver sensitivity, area trade-offs, diffusivity sensitivity, and voltage scheduling.

## 6. Direct-liquid receiver

Canonical implementation:
`scripts/make_wp1_direct_liquid_contact_receiver_v1.py`

This replaces the receiver gas stream with an idealised direct-liquid boundary and exposes liquid water activity as a receiver-state parameter.

## 7. Liquid-activity crossover

Canonical implementation:
`scripts/analyze_wp1_direct_liquid_activity_crossover_v1.py`

This compares the idealised free-liquid-removal boundary with the coupled gas-receiver reference as a function of liquid water activity.

## Interpretation

This repository contains research models rather than a validated product design.

Inverse-design material vectors are hypothetical unless separately supported by measurements. Generated simulation outputs should normally be reproducible from the source code rather than committed as raw result archives.
