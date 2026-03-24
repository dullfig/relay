; Hello World for the relay computer
; Prints "HELLO WORLD" to the Flexowriter via memory-mapped I/O
;
; Memory map:
;   $000-$0FF  Zero page (variables, stack)
;   $100-$EFF  Program and data
;   $FF0       Flexowriter data (write = print character)
;   $FF1       Flexowriter status (read: 0=ready, 1=busy)

.equ FLEX_DATA   $FF0
.equ FLEX_STATUS $FF1

.org $100

; Entry point
start:
        LDX #0              ; X = string index

loop:
        CLD                 ; binary mode for address math
        LDA message,X       ; load high nibble of ASCII char
        CMP #0              ; null terminator?
        BEQ done            ; yes -> stop
        STA FLEX_DATA       ; send high nibble to Flexowriter

        ; TODO: in reality we'd need to combine two nibbles into
        ; one ASCII byte and handle Flexowriter busy/ready.
        ; This is simplified - assumes the I/O interface
        ; assembles nibble pairs into bytes automatically.

        INC                 ; next nibble
        LDA message,X       ; load low nibble
        STA FLEX_DATA       ; send low nibble

        INC                 ; next character
        JMP loop

done:
        HLT

; String data: "HELLO WORLD" in ASCII nibble pairs
; H=48 E=45 L=4C L=4C O=4F space=20 W=57 O=4F R=52 L=4C D=44
.org $180
message:
        .ascii "HELLO WORLD"
        .byte $0 $0         ; null terminator (2 nibbles)
