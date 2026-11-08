//! `logscan`: read a CI log on stdin, print the error windows on stdout.
//!
//! Usage: logscan [--before N] [--after N] [--max N] < build.log

use std::io::{self, Read};
use std::process::ExitCode;

use logscan::{extract_windows, render, Options};

fn parse_args(args: &[String]) -> Result<Options, String> {
    let mut opts = Options::default();
    let mut it = args.iter();
    while let Some(flag) = it.next() {
        let target = match flag.as_str() {
            "--before" => &mut opts.before,
            "--after" => &mut opts.after,
            "--max" => &mut opts.max_windows,
            other => return Err(format!("unknown argument: {other}")),
        };
        let value = it.next().ok_or_else(|| format!("{flag} needs a value"))?;
        *target = value
            .parse()
            .map_err(|_| format!("{flag} expects a number, got {value:?}"))?;
    }
    Ok(opts)
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let opts = match parse_args(&args) {
        Ok(o) => o,
        Err(msg) => {
            eprintln!("logscan: {msg}\nusage: logscan [--before N] [--after N] [--max N]");
            return ExitCode::from(2);
        }
    };

    let mut log = String::new();
    if let Err(err) = io::stdin().read_to_string(&mut log) {
        eprintln!("logscan: cannot read stdin: {err}");
        return ExitCode::FAILURE;
    }

    print!("{}", render(&extract_windows(&log, &opts)));
    ExitCode::SUCCESS
}
