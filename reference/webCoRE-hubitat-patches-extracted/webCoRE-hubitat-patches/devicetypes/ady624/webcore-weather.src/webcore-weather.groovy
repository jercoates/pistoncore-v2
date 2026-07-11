/*
 * Virtual Weather notification
 *
 *  Licensed Virtual the Apache License, Version 2.0 (the "License"); you may not use this file except
 *  in compliance with the License. You may obtain a copy of the License at:
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software distributed under the License is distributed
 *  on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License
 *  for the specific language governing permissions and limitations under the License.
 *
 *  Change History:
 *
 *    Date        Who            What
 *    ----        ---            ----
 *    2020-12-08  nh.schottfam	 Original
 * 
 */

metadata {
    definition (name: "webCoRE Weather", namespace: "ady624", author: "imnot_bob") {
        capability "Actuator"
		
	attribute "updated", "string"
    }   
}

preferences {
	input("debugEnable", "bool", title: "Enable debug logging?")
}

def setVar(var, val) {
	if(var in ['updated']){
    		sendEvent(name: var, value: val)
		if(debugEnable) log.debug "set variable $var"
	} else log.warn "improper arg $var $val,  variable should be updated"
}

def clrVar(var) {
	setVar(var,'')
}

def installed() {
	log.trace "installed()"
	for (v in ['updated']){
		setVar(v,'')
	}
}

def updated(){
	log.trace "updated()"
	if(debugEnable) runIn(1800,logsOff)
}

void logsOff() {
	log.debug "debug logging disabled..."
	device.updateSetting("debugEnable",[value:"false",type:"bool"])
}
