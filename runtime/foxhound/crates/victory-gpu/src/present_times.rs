//! Optional application-present intervals. Generated frames are not counted.
use std::io::{BufWriter, Write};
use std::time::{Duration, Instant};

pub(crate) struct PresentTimes {
    output: BufWriter<std::fs::File>,
    start: Instant,
    previous: Option<Instant>,
    flushed: Instant,
}

impl PresentTimes {
    pub(crate) fn from_env() -> Option<Self> {
        let path = std::env::var_os("VICTORY_PRESENT_TIMES")?;
        let file = match std::fs::File::create(path) {
            Ok(file) => file,
            Err(error) => {
                tracing::warn!(%error, "could not open application present timings");
                return None;
            }
        };
        let mut output = BufWriter::with_capacity(64 * 1024, file);
        if writeln!(output, "elapsed_ms,interval_ms").is_err() {
            return None;
        }
        let now = Instant::now();
        Some(Self { output, start: now, previous: None, flushed: now })
    }

    // Called once for each application frame, independently of interpolation.
    // Buffer writes and flush once a second to keep the probe inexpensive.
    pub(crate) fn frame(&mut self) -> std::io::Result<()> {
        let now = Instant::now();
        if let Some(previous) = self.previous.replace(now) {
            writeln!(self.output, "{:.3},{:.3}",
                now.duration_since(self.start).as_secs_f64() * 1000.0,
                now.duration_since(previous).as_secs_f64() * 1000.0)?;
        }
        if now.duration_since(self.flushed) >= Duration::from_secs(1) {
            self.output.flush()?;
            self.flushed = now;
        }
        Ok(())
    }
}
