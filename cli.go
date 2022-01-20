package main

import (
	"fmt"
	"log"
	"os/exec"
	"strings"
)

func cli(path string, program string, command string, args string) (string, string, string) {

	argArr := strings.Split(args, " ")

	fullCmd := []string{program, command}

	fullCmd = append(fullCmd, argArr...)

	cmd := exec.Cmd{
		Path: path,
		Args: fullCmd,
	}

	for _, str := range cmd.Args {
		fmt.Printf("* %s\n", str)
	}

	out, err := cmd.CombinedOutput()
	if cmd.Stderr != nil {
		log.Print(cmd.Stderr)
	}

	resp := string(out)

	index := strings.Index(resp, "'new_contract'")

	contractNum := substr(resp, index+16, 7)

	fmt.Print("contract number: " + contractNum)

	return contractNum, string(out), err.Error()
}
func prependstring(x []string, y string) []string {
	x = append(x, y)
	copy(x[1:], x)
	x[0] = y
	return x
}
func substr(input string, start int, length int) string {
	asRunes := []rune(input)

	if start >= len(asRunes) {
		return ""
	}

	if start+length > len(asRunes) {
		length = len(asRunes) - start
	}

	return string(asRunes[start : start+length])
}
