import ssl

from capture.http import EXTRA_CA_FILE, build_ssl_context


def test_ssl_context_loads_extra_chain_and_keeps_verification_on():
    context = build_ssl_context()

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True

    subjects = {
        dict(rdn[0] for rdn in cert["subject"]).get("commonName")
        for cert in context.get_ca_certs()
    }
    assert {"YE2", "Root YE", "ISRG Root X2"} <= subjects
    assert EXTRA_CA_FILE.exists()
