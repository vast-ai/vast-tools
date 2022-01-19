package main

import (
	"fmt"

	"log"

	"github.com/hashicorp/terraform-plugin-sdk/helper/schema"
)

func resourceServer() *schema.Resource {
	return &schema.Resource{
		Create: resourceServerCreate,
		Read:   resourceServerRead,
		Update: resourceServerUpdate,
		Delete: resourceServerDelete,

		Schema: map[string]*schema.Schema{
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
	command := d.Get("command").(string)
	args := d.Get("arguments").(string)
	api_key := d.Get("api_key").(string)
	d.SetId(api_key)

	resp, err := cli(command, args)
	if err != "" {
		log.Print(err)
	}

	fmt.Print(resp)

	return resourceServerRead(d, m)
}

func resourceServerRead(d *schema.ResourceData, m interface{}) error {
	return nil
}

func resourceServerUpdate(d *schema.ResourceData, m interface{}) error {
	return resourceServerRead(d, m)
}

func resourceServerDelete(d *schema.ResourceData, m interface{}) error {
	d.SetId("")
	return nil
}
