package main

import (
	"fmt"
	//"log"
	"os/exec"
)

func cli(c string, arg string) (string, string) {

	command := c + " "
	if arg != "" {
		arg = "search offers"
	}
	fmt.Print(command + arg)

	cmd := exec.Cmd{
		Path: c,
		Args: []string{command, arg},
	}

	out, err := cmd.CombinedOutput()
	//if cmd.Stderr != nil {
	//	log.Panic(cmd.Stderr)
	//}

	return string(out), err.Error()
}
