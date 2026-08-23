# Discovery findings

What the **actual device** does, as opposed to what the API documentation and
the SDK source imply. Three assumptions in the design are load-bearing and can
only be settled by observation; this file is where the answers live.

Recorded from `airchive discover` on **2026-08-23**. Both commands are read-only
and issue no control command.

> **Gate B is still open.** Everything except the intraday-advance question and
> the day boundary is settled below. Run
> `airchive validate-counter --duration-minutes 240` while the air conditioner is
> in normal use to close it.

---

## 1. Device identity

| Field | Value |
|---|---|
| `deviceId` | `d7dc30c9698797295acbb90ee543447738db8f7b3d5cff230eb66978a855be3a` |
| Alias | `Air Conditioner` |
| Model name | `WIN_056905_WW` |
| Device type | `DEVICE_AIR_CONDITIONER` |
| Devices on the account | 1 (this one) |
| Recorded on | 2026-08-23 |

---

## 2. Energy property — settled

| Question | Answer |
|---|---|
| Properties in `energy_profile["result"]["property"]` | **`["energyUsage"]`** — one only |
| Property configured | `energyUsage` |
| Unit reported by the API | **none — the response carries no unit field at all** |
| Decimal places observed | **0** — the counter is a plain integer |
| Sample value | `462` for 2026-08-23 |

**The property is `energyUsage`, not `energyConsumption`.** The provisional
schema guessed the latter, and the design's instruction to read the name from
the device's own energy profile rather than hard-coding it is the only reason
this was caught before it became a silent failure.

Actual response shape:

```json
{
  "resultCode": "0000",
  "result": {
    "dataList": [
      { "usedDate": "20260823", "energyUsage": 462 }
    ],
    "property": ["energyUsage"]
  }
}
```

Three things here differ from every shape the extractor originally guessed:

- the record list is `dataList` (not `energyData`/`usageData`/…)
- the date key is `usedDate` (not `date`/`startDate`/…)
- the value key **is the property name itself**, `energyUsage`

The extractor reported *"no numeric reading could be located"* rather than
inventing a value — which is the behaviour the spec demands — and
`airchive/thinq/payloads.py` has since been reconciled against the real shape,
with a regression test pinned to this exact payload.

### The unit is unknown, and is recorded as unknown

The API reports no unit. `462` is stored with `unit: null`, because the spec
forbids assuming one. **Working hypothesis: watt-hours** — 462 Wh ≈ 0.46 kWh is
a plausible partial-day figure for a room AC, whereas 462 kWh in one day is not.

This is a hypothesis, not a finding. `validate-counter` settles it: a running
1–2 kW unit should add roughly 1,000–2,000 per hour if the unit is Wh, i.e.
~80–170 per five-minute slot. Record the observed rate below and update this
section.

### Consequence: integer arithmetic, zero decimal places

The counter has no fractional part, so interval deltas are whole numbers. The
`Decimal` pipeline handles this correctly — quantization takes its precision
from the source values, so a zero-decimal counter yields zero-decimal intervals
and no spurious digits appear. The `8.751 − 8.732 = 0.019` examples throughout
the docs are illustrative of the *arithmetic*, not of this device's values.

---

## 3. Gate B — does the current-day counter advance intraday?

**This is the assumption the entire project rests on.** The official API exposes
no instantaneous power property, so if LG only updates the daily counter once a
day, sub-daily energy resolution is impossible through a supported source and
the collector's value narrows to state-only history.

| Question | Answer |
|---|---|
| Does the value change within the day? | **_pending — run `validate-counter`_** |
| Observation window (start → end, hours) | |
| Number of intraday increases observed | |
| Smallest increment seen | |
| Apparent update latency (min / median / max between changes) | |
| Longest run of an unchanged value | |
| Evidence of cached or repeated values | |
| Retroactive downward revisions of an already-observed value | |
| Implied unit (see §2) | |

**Verdict:**

- [ ] **Passes** — the counter advances intraday; five-minute sampling is
      meaningful.
- [ ] **Fails** — revisit the proposal before relying on energy deltas.
      State-only telemetry may still proceed.

Paste the `validate-counter` summary output here:

```
(pending)
```

---

## 4. The LG day boundary — pending

The daily bucket resets on a timezone owned by LG and the device, which may not
be the collector's configured one. A wrong boundary silently corrupts every
day-rollover reconstruction.

| Question | Answer |
|---|---|
| Observed reset time (local clock) | _pending — needs a run across midnight_ |
| Configured `LG_DAY_TIMEZONE` | `Asia/Manila` |
| Do they agree? | |
| Any timezone the API itself exposes for the device or account | **none** — neither the profile, the state, nor the usage response carries a timezone |

The API exposing no timezone anywhere is itself a finding: the boundary can only
be established by observing when the counter resets, which is what the 24-hour
unattended run (task 9.7) is for. `usedDate` is a bare `YYYYMMDD` string with no
zone attached.

---

## 5. Readable state properties this model exposes — settled

The SDK defines twelve AC resource groups. This device populates ten of them.
The collector stores exactly what is returned and invents nothing.

| Resource group | Present? | Properties observed |
|---|---|---|
| `runState` | yes | `currentState` (`NORMAL`) |
| `operation` | yes | `airConOperationMode` (`POWER_ON`) |
| `airConJobMode` | yes | `currentJobMode` (`COOL`) |
| `temperature` | yes | `currentTemperature` 28, `targetTemperature` 26, `unit` `C`; profile also advertises `minTargetTemperature`, `maxTargetTemperature`, `coolTargetTemperature` |
| `temperatureInUnits` | yes | a **list** carrying both scales: 28/26 `C` and 82/78 `F` |
| `airFlow` | yes | `windStrength` (`MID`), `windStrengthDetail` (`MID`) |
| `filterInfo` | yes | `filterLifetime` 192, `usedTime` 58 |
| `timer` | yes | all four absolute/relative start/stop timers, `UNSET`; profile advertises hour/minute components too |
| `sleepTimer` | yes | `relativeStopTimer` `UNSET` |
| `display` | yes | `light` (`ON`) |
| `powerSave` | **no** | absent from both profile and state |
| `airQualitySensor` | **no** | absent — no humidity or air-quality readings |
| `windDirection` | **no** | absent |
| `twoSetTemperature` | **no** | absent |

Answers to the design's open questions:

- **`powerSaveEnabled` does not exist on this model**, as a boolean or
  otherwise. The proposal's illustrative `energyControl: 40` likewise does not
  appear — it is not in the SDK's AC vocabulary and not on this device. Nothing
  is stored for either; they are simply absent.
- **Temperature unit is `C`**, and `temperatureInUnits` supplies the Fahrenheit
  conversion alongside it. Both are preserved verbatim, so no unit conversion is
  ever performed by the collector.
- **No humidity and no air-quality data** are available from this unit.

---

## 6. Rate limits

| Question | Answer |
|---|---|
| Published per-token call quota | not stated in the API response |
| Headroom above ~576 calls/day for one device | unknown; no limiting observed during discovery |
| Any `1306 EXCEEDED_API_CALLS` seen during validation | none so far |

---

## 7. Reconciliation against the provisional schema

- [x] `LG_ENERGY_PROPERTY` matches a property the device really exposes —
      corrected from `energyConsumption` to `energyUsage`.
- [x] The stored `unit` matches what the API reports — it reports none, so
      `null` is stored rather than an assumed `kWh`.
- [x] Interval quantization matches the observed decimal precision — zero
      decimals, handled by taking precision from the source values.
- [x] The energy extractor handles the real response shape — `dataList` /
      `usedDate` / property-named value, with a regression test.
- [ ] `LG_DAY_TIMEZONE` matches the observed reset boundary — pending §4.
- [ ] The documented limitations in [operations.md](operations.md) match what
      was observed here — update once Gate B closes.
