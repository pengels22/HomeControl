from importlib import import_module

pairing = import_module('07_servises.common.pairing_glyph')


def test_pairing_glyph_round_trips_payload():
    glyph = pairing.encode_pairing_glyph('HCM01', '482913')

    assert glyph.size == 17
    assert glyph.payload == 'HC1:HCM01:482913'
    assert pairing.decode_pairing_glyph(glyph.matrix) == glyph.payload


def test_pairing_glyph_rejects_corrupt_matrix():
    glyph = pairing.encode_pairing_glyph('HCM01', '482913')
    matrix = list(glyph.matrix)
    row = list(matrix[8])
    row[8] = '1' if row[8] == '0' else '0'
    matrix[8] = ''.join(row)

    try:
        pairing.decode_pairing_glyph(matrix)
    except ValueError as exc:
        assert 'checksum' in str(exc)
    else:
        raise AssertionError('corrupt pairing glyph decoded successfully')
