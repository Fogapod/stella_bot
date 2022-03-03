use pyo3::prelude::*;

#[pyfunction]
fn matching_string_prefixes(string: &str, mut prefixes: Vec<String>) -> Vec<String> {
    let mut offset = 0;

    let prefixes = prefixes.as_mut_slice();

    for i in 0..prefixes.len() {
        if !string.starts_with(&prefixes[i]) {
            continue;
        }
        // it is unlikely for many prefixes to match from the beginning, so always clone
        prefixes[offset] = prefixes[i].clone();

        offset += 1;
    }

    prefixes[..offset].to_vec()
}

#[pymodule]
fn stellars(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(matching_string_prefixes, m)?)?;

    Ok(())
}
