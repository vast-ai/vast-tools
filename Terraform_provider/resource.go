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
				ForceNew: true,
				Required: true,
			},
			"command": &schema.Schema{
				Type:     schema.TypeString,
				ForceNew: true,
				Required: true,
			},
			"arguments": &schema.Schema{
				Type:     schema.TypeString,
				ForceNew: true,
				Optional: true,
			},
			"api_key": &schema.Schema{
				Type:     schema.TypeString,
				ForceNew: true,
				Required: true,
			},
			"contract": &schema.Schema{
				Type:     schema.TypeString,
				ForceNew: true,
				Optional: true,
			},
			"instance_type": &schema.Schema{
				Type:     schema.TypeString,
				Required: true,
			},
		},
	}
}

func resourceServerCreate(d *schema.ResourceData, m interface{}) error {
	program := d.Get("program").(string)
	command := d.Get("command").(string)
	instance_type := d.Get("instance_type").(string)
	query := ""

	authenticate(d, m)
	if strings.Contains(instance_type, "DLperf_high") {
		query = "'reliability > 0.99  num_gpus=4 gpu_ram > 24 total_flops > 100 pcie_bw > 10 cpu_ram > 127'"
	} else if strings.Contains(instance_type, "DLperf_med") {
		query = "'reliability > 0.99  num_gpus=2 gpu_ram > 12 total_flops > 75 pcie_bw > 10 cpu_ram > 127'"
	} else {
		query = "'reliability > 0.99  num_gpus=1 gpu_ram > 8 total_flops > 50 pcie_bw > 10 cpu_ram > 127'"
	}

	if query != "" {
		args, err1 := cliSearch("./vast", program, "search offers", query)

		if err1 != "" {
			log.Print(err1)
		}

		contract, resp, err := cli("./vast", program, command, args)

		d.SetId(contract)
		d.Set("contract", contract)

		if err != "" {
			log.Print(err)
		}

		fmt.Print(resp)

	}

	return resourceServerRead(d, m)
}

func resourceServerRead(d *schema.ResourceData, m interface{}) error {
	return nil
}

func resourceServerDelete(d *schema.ResourceData, m interface{}) error {
	program := d.Get("program").(string)
	command := "destroy instance"
	args := d.Id()

	authenticate(d, m)

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
func authenticate(d *schema.ResourceData, m interface{}) error {
	program := d.Get("program").(string)
	command := "set api_key"
	args := d.Get("args").(string)
	api_key := d.Get("api_key").(string)

	resp, err := cliAuth("./vast", program, command, args, api_key)

	if strings.Contains(resp, "Your api key has been saved in") {
		fmt.Print("authentication successful")
		return nil
	} else {
		//an error occured
		return errors.New(err)
	}

}
