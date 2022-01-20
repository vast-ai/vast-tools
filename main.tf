resource "example_server" "my-server-name" {
	command = "create instance"
    program = "./vast"
    arguments = "instance ID Here"
    api_key = API_KEY
}