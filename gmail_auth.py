import imaplib
import socket


def connect_imap(email_user: str, email_pass: str, server: str = "imap.gmail.com", port: int = 993, timeout: int = 20) -> imaplib.IMAP4_SSL:
    """
    Establish a logged-in IMAP SSL connection.

    Raises:
        ValueError: if credentials are missing.
        imaplib.IMAP4.error: on authentication or connection issues.
    """
    if not email_user or not email_pass:
        raise ValueError("EMAIL_USER and EMAIL_PASS must be provided")

    # Set a global socket timeout to avoid hanging network calls.
    socket.setdefaulttimeout(timeout)

    mail = imaplib.IMAP4_SSL(server, port)
    # Ensure the underlying socket has a timeout (imaplib can otherwise block on reads).
    try:
        mail.sock.settimeout(timeout)
    except Exception:
        pass
    mail.login(email_user, email_pass)
    return mail

