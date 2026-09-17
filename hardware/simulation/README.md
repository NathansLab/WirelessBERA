# LTspice simulations

The analog design work behind the front end. Open the `.asc` files in LTspice.

| File | What it answers |
|---|---|
| `AC_Simulation.asc` | frequency response of the instrumentation-amplifier chain |
| `Noise_Simulation.asc` | input-referred noise across the gain settings |
| `Transient_Simulation.asc` | step and settling behaviour of the signal path |
| `Transient_Simulation_DRL.asc` | driven-right-leg loop stability |
| `Transient_Simulation_CommonModeDRLTestbench.asc` | common-mode rejection with the DRL loop closed |
| `Transient_Simulation.plt` | saved plot configuration for the transient run |

`Signals/` holds the stimulus data:

- `BERA_signal_pwl.txt` — a single BERA epoch as an LTspice PWL source
- `BERA_signal_pwl_20sec_2000pulse.txt` — 2000 pulses over 20 s, for averaging runs
- `Typical BERA Waveforms.pdf` — reference waveforms the PWL files are modelled on

LTspice run output (`.log`, `.raw`) is not tracked — re-running a simulation
regenerates it.
