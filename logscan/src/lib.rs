//! Parse CI logs and extract the regions that matter.

/// Returns the number of lines that look like errors.
pub fn count_error_lines(log: &str) -> usize {
    log.lines()
        .filter(|line| line.to_ascii_lowercase().contains("error"))
        .count()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counts_error_lines_case_insensitively() {
        let log = "starting\nERROR: boom\nok\nerror[E0308]: mismatched types\n";
        assert_eq!(count_error_lines(log), 2);
    }

    #[test]
    fn empty_log_has_no_errors() {
        assert_eq!(count_error_lines(""), 0);
    }
}
