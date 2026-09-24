output "public_ip" {
  value = aws_eip.hub.public_ip
}

output "hostname" {
  description = "A TLS-able name with no DNS setup: <ip-with-dashes>.sslip.io"
  value       = "${replace(aws_eip.hub.public_ip, ".", "-")}.sslip.io"
}

output "url" {
  value = "https://${replace(aws_eip.hub.public_ip, ".", "-")}.sslip.io"
}

output "ssh" {
  value = "ssh ubuntu@${aws_eip.hub.public_ip}"
}

output "ansible_inventory" {
  description = "Paste into deploy/ansible/inventory.ini"
  value       = "[hub]\n${aws_eip.hub.public_ip} ansible_user=ubuntu sentinel_hostname=${replace(aws_eip.hub.public_ip, ".", "-")}.sslip.io\n"
}
