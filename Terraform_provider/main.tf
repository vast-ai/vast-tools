

resource "example_server" "my-server-name" {
	command = "create instance"
    program = "./vast"
    arguments = ""
    api_key = var.api_key
    instance_type = "DLperf_high" # Options = DLperf_high, DLperf_med, DLperf_low
    
}

output "contract" {
  value = "${example_server.my-server-name.contract}"
}

