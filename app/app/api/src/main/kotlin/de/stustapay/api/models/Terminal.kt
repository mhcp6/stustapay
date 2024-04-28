/**
 *
 * Please note:
 * This class is auto generated by OpenAPI Generator (https://openapi-generator.tech).
 * Do not edit this file manually.
 *
 */

@file:Suppress(
    "ArrayInDataClass",
    "EnumEntryName",
    "RemoveRedundantQualifierName",
    "UnusedImport"
)

package de.stustapay.api.models


import kotlinx.serialization.Serializable
import kotlinx.serialization.SerialName
import kotlinx.serialization.Contextual

/**
 * 
 *
 * @param name 
 * @param id 
 * @param nodeId 
 * @param tillId 
 * @param sessionUuid 
 * @param registrationUuid 
 * @param description 
 */
@Serializable

data class Terminal (

    @SerialName(value = "name")
    val name: kotlin.String,

    @SerialName(value = "id")
    val id: @Contextual com.ionspin.kotlin.bignum.integer.BigInteger,

    @SerialName(value = "node_id")
    val nodeId: @Contextual com.ionspin.kotlin.bignum.integer.BigInteger,

    @SerialName(value = "till_id")
    val tillId: @Contextual com.ionspin.kotlin.bignum.integer.BigInteger?,

    @Contextual @SerialName(value = "session_uuid")
    val sessionUuid: java.util.UUID?,

    @Contextual @SerialName(value = "registration_uuid")
    val registrationUuid: java.util.UUID?,

    @SerialName(value = "description")
    val description: kotlin.String? = null

)
