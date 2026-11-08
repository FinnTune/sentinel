package gateway

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"testing"
)

func sign(secret string, body []byte) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return "sha256=" + hex.EncodeToString(mac.Sum(nil))
}

func TestVerifySignature(t *testing.T) {
	body := []byte(`{"hello":"world"}`)
	valid := sign("s3cret", body)

	tests := []struct {
		name   string
		secret string
		body   []byte
		header string
		want   bool
	}{
		{"valid", "s3cret", body, valid, true},
		{"wrong secret", "other", body, valid, false},
		{"tampered body", "s3cret", []byte(`{"hello":"mars"}`), valid, false},
		{"missing header", "s3cret", body, "", false},
		{"missing prefix", "s3cret", body, valid[len(signaturePrefix):], false},
		{"not hex", "s3cret", body, "sha256=zzzz", false},
		{"truncated", "s3cret", body, valid[:len(valid)-2], false},
		{"empty secret fails closed", "", body, sign("", body), false},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := VerifySignature(tc.secret, tc.body, tc.header); got != tc.want {
				t.Fatalf("VerifySignature() = %v, want %v", got, tc.want)
			}
		})
	}
}
