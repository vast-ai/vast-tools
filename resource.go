package main

import (
	"errors"
	"fmt"
	"strings"

	"log"

	"github.com/hashicorp/terraform-plugin-sdk/helper/schema"
)

func resourceServer() *schema.Resource {
	return &schema.Resource{
		Create: resourceServerCreate,
		Read:   resourceServerRead,

		Delete: resourceServerDelete,

		Schema: map[string]*schema.Schema{
			"program": &schema.Schema{
				Type:     schema.TypeString,
				Required: true,
			},
			"command": &schema.Schema{
				Type:     schema.TypeString,
				Required: true,
			},
			"arguments": &schema.Schema{
				Type:     schema.TypeString,
				Required: true,
			},
			"api_key": &schema.Schema{
				Type:     schema.TypeString,
				Required: true,
			},
		},
	}
}

func resourceServerCreate(d *schema.ResourceData, m interface{}) error {
	program := d.Get("program").(string)
	command := d.Get("command").(string)
	args := d.Get("arguments").(string)

	contract, resp, err := cli("./vast", program, command, args)

	d.SetId(contract)

	if err != "" {
		log.Print(err)
	}

	fmt.Print(resp)

	return resourceServerRead(d, m)
}

func resourceServerRead(d *schema.ResourceData, m interface{}) error {
	return nil
}

func resourceServerDelete(d *schema.ResourceData, m interface{}) error {
	program := d.Get("program").(string)
	command := "destroy instance"
	args := d.Id()

	contract, resp, err := cli("./vast", program, command, args)

	if strings.Contains(resp, "destroying") {
		fmt.Print("Contract: " + contract + "terminated")
		d.SetId("")
		return nil
	} else {
		//an error occured
		return errors.New(err)
	}

}
