package gateway

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"strings"
)

const signaturePrefix = "sha256="

// VerifySignature reports whether header is a valid GitHub X-Hub-Signature-256
// value for body under secret. It fails closed: an empty secret never verifies,
// and the comparison is constant-time.
func VerifySignature(secret string, body []byte, header string) bool {
	if secret == "" {
		return false
	}
	hexSig, ok := strings.CutPrefix(header, signaturePrefix)
	if !ok {
		return false
	}
	got, err := hex.DecodeString(hexSig)
	if err != nil {
		return false
	}
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return hmac.Equal(got, mac.Sum(nil))
}
