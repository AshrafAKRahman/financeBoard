# Backlog

Work that is specified or understood but deliberately not being built yet. Each entry says
why it is parked and what it needs to start, so picking it up does not mean starting over.

---

## ZATCA e-invoicing (FATOORA) — parked 2026-09-18

**Why parked:** it needs Fatoora portal credentials (an OTP to onboard a device), and one
open question about ZATCA's own rules. Invoicing works without it, so it is not blocking
the rest of Phase 1.

**Legal note:** a Saudi company cannot issue compliant tax invoices without this. It is the
last thing to finish before the system could be used for real trading in Saudi Arabia, even
though it is not the next thing to build.

### What it covers

- UBL 2.1 XML for each invoice, credit note and debit note.
- Cryptographic stamp: ECDSA secp256k1 key per device, CSR, compliance CSID, production CSID.
- Invoice hash chain: each document carries a counter (ICV) and the previous invoice's hash
  (PIH), per issuing device.
- QR code (TLV) on simplified invoices and their printed receipts.
- **Standard (B2B) invoices: clearance** — submitted and cleared by ZATCA before the buyer
  gets them.
- **Simplified (B2C) invoices: reporting** — issued immediately, reported within 24 hours.
- Submission queue with retries, and an immutable archive of the signed and cleared XML.
- Bilingual (Arabic/English) invoice PDF carrying the QR code.

### What it needs before starting

1. **Fatoora portal access** — an OTP to onboard a device in the sandbox, then in
   simulation, then production CSIDs.
2. **Decision D4 confirmation** — how ZATCA expects the invoice counter and hash chain to
   continue after a rejected document. The current design locks the rejected invoice and
   issues a corrected copy with a new number; whether the counter and chain skip or reuse
   the rejected entry needs checking against ZATCA's specification.
3. **ZATCA's own SDK** (a Java tool) to validate generated XML in CI. Java 17 is already
   installed on this machine.

### What is already in place for it

- Every posted document stores what a tax invoice needs: seller VAT number on the company,
  buyer VAT and CR numbers on the partner, per-line tax category and exemption reason, and
  totals grouped per tax.
- Totals come from one pure function, so the XML will report exactly what the ledger holds.
- Documents are immutable once issued, which is what ZATCA assumes.
- The architecture document (§8.2) already has the issuing flow, the EGS unit model, the
  `zatca_document` table shape and the error codes.
- Decisions D2 (per-line tax rounding) and D3 (tax-inclusive pricing) were made with
  ZATCA's arithmetic in mind.

### Rough size

Comparable to `invoicing-and-vat`: one migration, a signing and XML module, a submission
client with a recorded transport for tests, an onboarding wizard, and the PDF. The
cryptography and canonicalisation are the risky parts, which is why validating against
ZATCA's SDK is a requirement rather than a nicety.
