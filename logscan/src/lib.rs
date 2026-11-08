//! Parse CI logs and extract the regions that matter.
//!
//! The pipeline: strip ANSI escapes, find error lines, grow each into a
//! window of surrounding context, merge overlapping windows, then collapse
//! windows with identical content into one with a repeat count.

use std::collections::HashMap;

/// Substrings (matched case-insensitively) that mark a line as an error.
const ERROR_MARKERS: [&str; 7] = [
    "error",
    "fatal",
    "panic",
    "exception",
    "traceback",
    "failed",
    "failure",
];

/// How much context to keep around each error line.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Options {
    /// Lines of context kept before an error line.
    pub before: usize,
    /// Lines of context kept after an error line.
    pub after: usize,
    /// Maximum number of windows returned (the earliest are kept).
    pub max_windows: usize,
}

impl Default for Options {
    fn default() -> Self {
        Self {
            before: 3,
            after: 5,
            max_windows: 20,
        }
    }
}

/// A contiguous region of the log around one or more error lines.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Window {
    /// First line of the window (1-based, inclusive).
    pub start_line: usize,
    /// Last line of the window (1-based, inclusive).
    pub end_line: usize,
    /// The window's lines, ANSI escapes removed.
    pub lines: Vec<String>,
    /// How many windows with identical content were collapsed into this one.
    pub repeats: usize,
}

/// Remove ANSI escape sequences (colors, cursor movement) from `input`.
pub fn strip_ansi(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    let mut chars = input.chars().peekable();
    while let Some(c) = chars.next() {
        if c != '\u{1b}' {
            out.push(c);
            continue;
        }
        // CSI sequence: ESC [ params final-byte(0x40..=0x7e)
        if chars.peek() == Some(&'[') {
            chars.next();
            for next in chars.by_ref() {
                if ('\u{40}'..='\u{7e}').contains(&next) {
                    break;
                }
            }
        }
        // A bare ESC followed by anything else is dropped on its own.
    }
    out
}

/// Whether a line looks like an error. Matching is a case-insensitive
/// substring check, so it is deliberately broad (e.g. "0 failed" matches).
pub fn is_error_line(line: &str) -> bool {
    let lower = line.to_ascii_lowercase();
    ERROR_MARKERS.iter().any(|m| lower.contains(m))
}

/// Returns the number of lines that look like errors.
pub fn count_error_lines(log: &str) -> usize {
    log.lines().filter(|line| is_error_line(line)).count()
}

/// Extract deduplicated error windows from `log`.
pub fn extract_windows(log: &str, opts: &Options) -> Vec<Window> {
    let lines: Vec<String> = log.lines().map(strip_ansi).collect();
    if lines.is_empty() {
        return Vec::new();
    }
    let last = lines.len() - 1;

    // Grow each error line into an inclusive 0-based range, merging overlaps.
    let mut ranges: Vec<(usize, usize)> = Vec::new();
    for (i, line) in lines.iter().enumerate() {
        if !is_error_line(line) {
            continue;
        }
        let start = i.saturating_sub(opts.before);
        let end = (i + opts.after).min(last);
        match ranges.last_mut() {
            Some(prev) if start <= prev.1 + 1 => prev.1 = prev.1.max(end),
            _ => ranges.push((start, end)),
        }
    }

    // Collapse windows whose content is identical, keeping first occurrence.
    let mut windows: Vec<Window> = Vec::new();
    let mut seen: HashMap<Vec<String>, usize> = HashMap::new();
    for (start, end) in ranges {
        let content = lines[start..=end].to_vec();
        if let Some(&idx) = seen.get(&content) {
            windows[idx].repeats += 1;
            continue;
        }
        seen.insert(content.clone(), windows.len());
        windows.push(Window {
            start_line: start + 1,
            end_line: end + 1,
            lines: content,
            repeats: 1,
        });
    }

    windows.truncate(opts.max_windows);
    windows
}

/// Render windows as plain text for use in a prompt.
pub fn render(windows: &[Window]) -> String {
    let mut out = String::new();
    for w in windows {
        out.push_str(&format!("--- lines {}-{}", w.start_line, w.end_line));
        if w.repeats > 1 {
            out.push_str(&format!(" (seen {} times)", w.repeats));
        }
        out.push_str(" ---\n");
        for line in &w.lines {
            out.push_str(line);
            out.push('\n');
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn opts(before: usize, after: usize) -> Options {
        Options {
            before,
            after,
            max_windows: 20,
        }
    }

    #[test]
    fn counts_error_lines_case_insensitively() {
        let log = "starting\nERROR: boom\nok\nerror[E0308]: mismatched types\n";
        assert_eq!(count_error_lines(log), 2);
    }

    #[test]
    fn empty_log_has_no_errors() {
        assert_eq!(count_error_lines(""), 0);
        assert!(extract_windows("", &Options::default()).is_empty());
    }

    #[test]
    fn strips_color_codes() {
        assert_eq!(strip_ansi("\u{1b}[31;1merror\u{1b}[0m: bad"), "error: bad");
        assert_eq!(strip_ansi("plain"), "plain");
    }

    #[test]
    fn detects_errors_hidden_behind_color_codes() {
        let log = "ok\n\u{1b}[31mFATAL\u{1b}[0m crash\nok\n";
        let w = extract_windows(log, &opts(0, 0));
        assert_eq!(w.len(), 1);
        assert_eq!(w[0].lines, vec!["FATAL crash"]);
    }

    #[test]
    fn window_includes_context_and_line_numbers() {
        let log = "a\nb\nc\nerror: x\nd\ne\nf\n";
        let w = extract_windows(log, &opts(2, 1));
        assert_eq!(w.len(), 1);
        assert_eq!((w[0].start_line, w[0].end_line), (2, 5));
        assert_eq!(w[0].lines, vec!["b", "c", "error: x", "d"]);
    }

    #[test]
    fn window_is_clamped_to_log_bounds() {
        let w = extract_windows("error: first\nx\n", &opts(5, 5));
        assert_eq!((w[0].start_line, w[0].end_line), (1, 2));
    }

    #[test]
    fn overlapping_and_adjacent_windows_merge() {
        let log = "error: one\nmid\nerror: two\nz\n";
        let w = extract_windows(log, &opts(0, 1));
        assert_eq!(w.len(), 1);
        assert_eq!((w[0].start_line, w[0].end_line), (1, 4));
    }

    #[test]
    fn identical_windows_collapse_with_repeat_count() {
        let log = "error: flaky\nok\n\nerror: flaky\nok\n\nerror: other\n";
        let w = extract_windows(log, &opts(0, 1));
        assert_eq!(w.len(), 2);
        assert_eq!(w[0].repeats, 2);
        assert_eq!(w[1].repeats, 1);
    }

    #[test]
    fn max_windows_keeps_the_earliest() {
        let log = "error: a\n\n\nerror: b\n\n\nerror: c\n";
        let o = Options {
            before: 0,
            after: 0,
            max_windows: 2,
        };
        let w = extract_windows(log, &o);
        assert_eq!(w.len(), 2);
        assert_eq!(w[1].lines, vec!["error: b"]);
    }

    #[test]
    fn render_marks_repeats() {
        let w = extract_windows("error: x\n\nerror: x\n", &opts(0, 0));
        let text = render(&w);
        assert!(text.starts_with("--- lines 1-1 (seen 2 times) ---\nerror: x\n"));
    }
}
