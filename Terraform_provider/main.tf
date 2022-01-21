resource "vast_instance" "contract" {
	command = "create instance"
    program = "./vast"
    arguments = "instance ID Here"
    api_key = API_KEY
}