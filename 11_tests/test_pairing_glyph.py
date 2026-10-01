from importlib import import_module

pairing = import_module('07_servises.common.pairing_glyph')


def test_pairing_glyph_round_trips_payload():
    glyph = pairing.encode_pairing_glyph('HCM01', '482913', 'test-secret')

    assert glyph.size == 33
    assert glyph.payload.startswith('HC2:')
    assert pairing.decode_pairing_glyph(glyph.matrix) == glyph.payload
    assert pairing.verify_secure_pairing_payload(glyph.payload, 'HCM01', '482913', 'test-secret')
    assert not pairing.verify_secure_pairing_payload(glyph.payload, 'HCM01', '000000', 'test-secret')
    assert not pairing.verify_secure_pairing_payload(glyph.payload, 'HCM01', '482913', 'wrong-secret')


def test_pairing_glyph_rejects_corrupt_matrix():
    glyph = pairing.encode_pairing_glyph('HCM01', '482913', 'test-secret')
    matrix = list(glyph.matrix)
    x, y = pairing._data_cells()[0]
    row = list(matrix[y])
    row[x] = '1' if row[x] == '0' else '0'
    matrix[y] = ''.join(row)

    try:
        pairing.decode_pairing_glyph(matrix)
    except ValueError as exc:
        assert 'checksum' in str(exc) or 'incomplete' in str(exc)
    else:
        raise AssertionError('corrupt pairing glyph decoded successfully')
