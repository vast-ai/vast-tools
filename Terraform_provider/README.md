# vast-tools
Vast-ai public repository for open sourced tools, plugins, etc.
Initial setup
install terraform
install go
navigate to project folder in terminal
run go mod init
run go mod tidy
dependencies should be satisfied

create a file called var.tf
create a variable
variable "API_KEY" {
  type = string
  default = "****"
  sensitive = true # this tag ensures the key is not exposed in log.
} 
IMPORTANT - do not commit this file
