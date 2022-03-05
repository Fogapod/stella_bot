use pyo3::prelude::*;
use pyo3::types::PySequence;
use std::str;

// linear search, slow
#[pyfunction]
unsafe fn matching_string_prefixes_v0<'a>(
    string: &str,
    mut prefixes: Vec<&'a str>,
) -> Vec<&'a str> {
    let mut prefixes_moved = 0;

    for i in 0..prefixes.len() {
        let prefix = prefixes.get_unchecked(i);

        if prefix.len() > string.len() || !string.starts_with(prefix) {
            continue;
        }
        *prefixes.get_unchecked_mut(prefixes_moved) = prefix;

        prefixes_moved += 1;
    }

    prefixes[..prefixes_moved].to_vec()
}

// i dont remember
#[pyfunction]
unsafe fn matching_string_prefixes_bytes_not_working<'a>(
    string: &'a [u8],
    prefixes: Vec<&'a [u8]>,
) -> Vec<&'a str> {
    let mut matches: Vec<&str> = Vec::with_capacity(prefixes.len());

    for i in 1..string.len() + 1 {
        if let Ok(index) =
            prefixes.binary_search_by(|&prefix| prefix.cmp(&string.get_unchecked(..i)))
        {
            matches.push(str::from_utf8_unchecked(prefixes.get_unchecked(index)));
        }
    }

    matches
}

// fastest
#[pyfunction]
unsafe fn matching_string_prefixes_stella_binary<'a>(
    string: &'a [u8],
    prefixes: Vec<&'a [u8]>,
) -> Vec<&'a str> {
    let mut matches: Vec<&str> = Vec::with_capacity(prefixes.len());

    for i in 1..string.len() - 1 {
        if let Ok(index) =
            prefixes.binary_search_by(|&prefix| prefix.cmp(&string.get_unchecked(..i)))
        {
            matches.push(str::from_utf8_unchecked(prefixes.get_unchecked(index)));
        }
    }

    matches
}

// slow
#[pyfunction]
unsafe fn matching_string_prefixes_stella_binary_native_type<'a>(
    string: &'a [u8],
    prefixes: &'a PySequence,
) -> Vec<&'a str> {
    let input: Vec<&[u8]> = prefixes
        .iter()
        .unwrap()
        .map(|item| item.unwrap().extract::<&[u8]>().unwrap())
        .collect();
    let mut matches: Vec<&str> = Vec::with_capacity(prefixes.len().unwrap());

    for i in 1..string.len() - 1 {
        if let Ok(index) = input.binary_search_by(|&prefix| prefix.cmp(&string.get_unchecked(..i)))
        {
            matches.push(str::from_utf8_unchecked(input.get_unchecked(index)));
        }
    }

    matches
}

#[pymodule]
fn stellars(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(matching_string_prefixes_v0, m)?)?;
    m.add_function(wrap_pyfunction!(matching_string_prefixes_stella_binary, m)?)?;
    m.add_function(wrap_pyfunction!(
        matching_string_prefixes_stella_binary_native_type,
        m
    )?)?;

    Ok(())
}
